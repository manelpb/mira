"""Ensemble merge logic and engine wiring."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from mira.config import MiraConfig
from mira.core.engine import ReviewEngine
from mira.core.ensemble import cross_model_merge, merge_ensemble_runs
from mira.llm.provider import LLMProvider
from mira.models import ReviewComment, Severity


def _comment(
    line: int,
    title: str = "Issue",
    confidence: float = 0.9,
    category: str = "bug",
    path: str = "app.py",
) -> ReviewComment:
    return ReviewComment(
        path=path,
        line=line,
        end_line=None,
        severity=Severity.WARNING,
        category=category,
        title=title,
        body="body text here",
        confidence=confidence,
    )


class TestMergeEnsembleRuns:
    def test_single_run_passthrough(self):
        run = [_comment(1), _comment(2)]
        assert merge_ensemble_runs([run]) == run
        assert merge_ensemble_runs([]) == []

    def test_majority_vote_2_of_3(self):
        recurring = lambda: _comment(10, "Null deref on user")  # noqa: E731
        flicker = _comment(50, "Speculative race condition")
        merged = merge_ensemble_runs([[recurring(), flicker], [recurring()], [recurring()]])
        assert len(merged) == 1
        assert merged[0].title == "Null deref on user"

    def test_all_runs_agree_keeps_everything(self):
        runs = [[_comment(10, "A"), _comment(20, "B")] for _ in range(3)]
        merged = merge_ensemble_runs(runs)
        assert {c.title for c in merged} == {"A", "B"}

    def test_confidence_is_cluster_mean(self):
        runs = [
            [_comment(10, "A", confidence=0.9)],
            [_comment(10, "A", confidence=0.7)],
            [_comment(10, "A", confidence=0.8)],
        ]
        merged = merge_ensemble_runs(runs)
        assert merged[0].confidence == 0.8

    def test_representative_is_highest_confidence_member(self):
        weak = _comment(10, "A", confidence=0.6)
        strong = _comment(10, "A", confidence=0.95)
        strong.suggestion = "the good fix"
        merged = merge_ensemble_runs([[weak], [strong]])
        assert merged[0].suggestion == "the good fix"

    def test_distinct_findings_do_not_cluster(self):
        # Same line, different category = distinct findings (noise_filter rule)
        leak = _comment(10, "Resource leak", category="resource-leak")
        injection = _comment(10, "SQL injection", category="security")
        merged = merge_ensemble_runs([[leak, injection], [leak, injection]], min_votes=2)
        assert len(merged) == 2

    def test_explicit_min_votes(self):
        once = _comment(10, "A")
        merged = merge_ensemble_runs([[once], [], []], min_votes=1)
        assert len(merged) == 1


class TestCrossModelMerge:
    def test_union_of_unrelated_findings(self):
        primary = [_comment(1, "P-only")]
        secondary = [_comment(99, "S-only")]
        merged, audit = cross_model_merge(primary, secondary)
        assert {c.title for c in merged} == {"P-only", "S-only"}
        assert audit["primary_only"] == 1
        assert audit["secondary_only"] == 1
        assert audit["matched"] == 0

    def test_match_within_line_tolerance_boosts_confidence(self):
        primary = [_comment(10, "X", confidence=0.8)]
        secondary = [_comment(12, "X", confidence=0.6)]  # same line ±3, same category
        merged, audit = cross_model_merge(primary, secondary)
        assert len(merged) == 1
        assert merged[0].confidence == pytest.approx(0.7)
        assert audit["matched"] == 1

    def test_match_outside_line_tolerance_does_not_merge(self):
        primary = [_comment(10, "X", confidence=0.8)]
        secondary = [_comment(20, "X", confidence=0.6)]  # |10-20| > 3
        merged, audit = cross_model_merge(primary, secondary)
        assert len(merged) == 2
        assert audit["matched"] == 0

    def test_different_category_does_not_merge(self):
        primary = [_comment(10, "X", category="bug")]
        secondary = [_comment(10, "X", category="security")]
        merged, _ = cross_model_merge(primary, secondary)
        assert len(merged) == 2

    def test_different_path_does_not_merge(self):
        primary = [_comment(10, "X", path="a.py")]
        secondary = [_comment(10, "X", path="b.py")]
        merged, _ = cross_model_merge(primary, secondary)
        assert len(merged) == 2

    def test_empty_inputs(self):
        assert cross_model_merge([], [])[0] == []
        p_result, _ = cross_model_merge([_comment(1, "P")], [])
        s_result, _ = cross_model_merge([], [_comment(1, "S")])
        assert p_result[0].title == "P"
        assert s_result[0].title == "S"

    def test_source_model_attribution(self):
        primary = [_comment(1, "P-only")]
        secondary = [_comment(99, "S-only")]
        merged, _ = cross_model_merge(primary, secondary)
        by_title = {c.title: c for c in merged}
        assert by_title["P-only"]._source_model == "primary"
        assert by_title["S-only"]._source_model == "secondary"

    def test_matched_finding_keeps_higher_severity_representative(self):
        primary = [_comment(10, "X", confidence=0.8)]
        primary[0].severity = Severity.WARNING
        secondary = [_comment(10, "X", confidence=0.6)]
        secondary[0].severity = Severity.BLOCKER
        merged, _ = cross_model_merge(primary, secondary)
        assert merged[0].severity == Severity.BLOCKER
        assert merged[0]._source_model == "secondary"

    def test_tie_break_primary_wins_on_equal_severity(self):
        primary = [_comment(10, "X", confidence=0.8)]
        secondary = [_comment(10, "X", confidence=0.6)]
        # Both default to WARNING, so `p.severity >= s.severity` -> primary wins.
        merged, _ = cross_model_merge(primary, secondary)
        assert len(merged) == 1
        assert merged[0]._source_model == "primary"
        assert merged[0].confidence == pytest.approx(0.7)

    def test_line_tolerance_boundary_three_matches_four_does_not(self):
        boundary_match, _ = cross_model_merge(
            [_comment(10, "X")],
            [_comment(13, "X")],  # |10-13| == 3
        )
        assert len(boundary_match) == 1

        just_over, _ = cross_model_merge(
            [_comment(10, "X")],
            [_comment(14, "X")],  # |10-14| == 4
        )
        assert len(just_over) == 2

    def test_custom_line_tolerance(self):
        primary = [_comment(10, "X")]
        secondary = [_comment(17, "X")]  # |10-17| == 7, beyond default 3
        # With default tolerance, they would not match.
        default_merged, _ = cross_model_merge(primary, secondary)
        assert len(default_merged) == 2
        # With line_tolerance=10, they do match.
        widened_merged, audit = cross_model_merge(primary, secondary, line_tolerance=10)
        assert len(widened_merged) == 1
        assert audit["matched"] == 1

    def test_inputs_are_not_mutated(self):
        primary = [_comment(1, "P-only")]
        secondary = [_comment(99, "S-only")]
        original_p = primary[0]
        original_s = secondary[0]
        merged, _ = cross_model_merge(primary, secondary)
        # Inputs keep their default _source_model (untouched).
        assert original_p._source_model == ""
        assert original_s._source_model == ""
        # And the returned merged items are distinct objects from the inputs.
        merged_by_title = {c.title: c for c in merged}
        assert merged_by_title["P-only"] is not original_p
        assert merged_by_title["S-only"] is not original_s
        # Tagging only happens on the copies.
        assert merged_by_title["P-only"]._source_model == "primary"
        assert merged_by_title["S-only"]._source_model == "secondary"


def _review_response(comments: list[dict]) -> str:
    return json.dumps({"comments": comments, "summary": "s", "metadata": {}})


def _raw(line: int, title: str, severity: str = "warning") -> dict:
    return {
        "path": "src/utils.py",
        "line": line,
        "end_line": None,
        "severity": severity,
        "category": "bug",
        "title": title,
        "body": f"Body for {title}",
        "confidence": 0.9,
        "existing_code": "x",
    }


class TestEnsembleEngineWiring:
    @pytest.mark.asyncio
    async def test_three_runs_consensus(self, sample_diff_text: str):
        config = MiraConfig()
        config.review.ensemble_runs = 3
        config.review.walkthrough = False
        config.review.security_pass = False
        config.review.self_critique = False
        config.review.include_summary = False
        config.review.code_context = False

        responses = [
            _review_response([_raw(9, "Recurring A"), _raw(16, "Recurring B")]),
            _review_response([_raw(9, "Recurring A"), _raw(21, "One-off C")]),
            _review_response([_raw(16, "Recurring B"), _raw(9, "Recurring A")]),
        ]
        llm = MagicMock(spec=LLMProvider)
        llm.review = AsyncMock(side_effect=responses)
        llm.complete = AsyncMock(return_value="")
        llm.count_tokens = MagicMock(return_value=100)
        llm.usage = {"total_tokens": 300}

        engine = ReviewEngine(config=config, llm=llm)
        result = await engine.review_diff(sample_diff_text)

        assert llm.review.call_count == 3
        titles = {c.title for c in result.comments}
        assert titles == {"Recurring A", "Recurring B"}

        # Extra runs sample at the ensemble temperature.
        temps = [c.kwargs.get("temperature") for c in llm.review.call_args_list]
        assert temps.count(0.3) == 2

    @pytest.mark.asyncio
    async def test_failed_extra_run_degrades_gracefully(self, sample_diff_text: str):
        config = MiraConfig()
        config.review.ensemble_runs = 3
        config.review.walkthrough = False
        config.review.security_pass = False
        config.review.self_critique = False
        config.review.include_summary = False
        config.review.code_context = False

        responses = [
            _review_response([_raw(9, "Recurring A")]),
            RuntimeError("LLM down"),
            _review_response([_raw(9, "Recurring A")]),
        ]
        llm = MagicMock(spec=LLMProvider)
        llm.review = AsyncMock(side_effect=responses)
        llm.complete = AsyncMock(return_value="")
        llm.count_tokens = MagicMock(return_value=100)
        llm.usage = {"total_tokens": 300}

        engine = ReviewEngine(config=config, llm=llm)
        result = await engine.review_diff(sample_diff_text)

        # 2 surviving runs, finding present in both — kept.
        assert {c.title for c in result.comments} == {"Recurring A"}

    @pytest.mark.asyncio
    async def test_default_config_is_single_run(self, sample_diff_text: str):
        config = MiraConfig()
        config.review.walkthrough = False
        config.review.security_pass = False
        config.review.self_critique = False
        config.review.include_summary = False
        config.review.code_context = False

        llm = MagicMock(spec=LLMProvider)
        llm.review = AsyncMock(return_value=_review_response([_raw(9, "A")]))
        llm.complete = AsyncMock(return_value="")
        llm.count_tokens = MagicMock(return_value=100)
        llm.usage = {"total_tokens": 100}

        engine = ReviewEngine(config=config, llm=llm)
        await engine.review_diff(sample_diff_text)
        assert llm.review.call_count == 1


class TestMultiModelEngineWiring:
    @pytest.mark.asyncio
    async def test_secondary_model_runs_and_unions(self, sample_diff_text: str):
        config = MiraConfig()
        config.llm.secondary_review_model = "openai/gpt-4o"
        config.review.walkthrough = False
        config.review.security_pass = False
        config.review.self_critique = False
        config.review.include_summary = False
        config.review.code_context = False

        primary_resp = _review_response([_raw(9, "PrimaryUnique")])
        secondary_resp = _review_response([_raw(20, "SecondaryUnique")])

        primary = MagicMock(spec=LLMProvider)
        primary.review = AsyncMock(return_value=primary_resp)
        primary.complete = AsyncMock(return_value="")
        primary.count_tokens = MagicMock(return_value=100)
        primary.usage = {"total_tokens": 100}

        secondary = MagicMock(spec=LLMProvider)
        secondary.review = AsyncMock(return_value=secondary_resp)
        secondary.complete = AsyncMock(return_value="")
        secondary.count_tokens = MagicMock(return_value=100)
        secondary.usage = {"total_tokens": 100}

        engine = ReviewEngine(config=config, llm=primary, secondary_llm=secondary)
        result = await engine.review_diff(sample_diff_text)

        assert secondary.review.await_count >= 1
        titles = {c.title for c in result.comments}
        assert "PrimaryUnique" in titles
        assert "SecondaryUnique" in titles

    @pytest.mark.asyncio
    async def test_secondary_failure_falls_back_to_primary(self, sample_diff_text: str):
        config = MiraConfig()
        config.llm.secondary_review_model = "openai/gpt-4o"
        config.review.walkthrough = False
        config.review.security_pass = False
        config.review.self_critique = False
        config.review.include_summary = False
        config.review.code_context = False

        primary = MagicMock(spec=LLMProvider)
        primary.review = AsyncMock(return_value=_review_response([_raw(9, "OnlyPrimary")]))
        primary.complete = AsyncMock(return_value="")
        primary.count_tokens = MagicMock(return_value=100)
        primary.usage = {"total_tokens": 100}

        secondary = MagicMock(spec=LLMProvider)
        secondary.review = AsyncMock(side_effect=RuntimeError("LLM down"))
        secondary.complete = AsyncMock(return_value="")
        secondary.count_tokens = MagicMock(return_value=100)
        secondary.usage = {"total_tokens": 0}

        engine = ReviewEngine(config=config, llm=primary, secondary_llm=secondary)
        result = await engine.review_diff(sample_diff_text)

        assert {c.title for c in result.comments} == {"OnlyPrimary"}

    @pytest.mark.asyncio
    async def test_no_secondary_when_config_unset(self, sample_diff_text: str):
        config = MiraConfig()
        assert config.llm.secondary_review_model is None
        config.review.walkthrough = False
        config.review.security_pass = False
        config.review.self_critique = False
        config.review.include_summary = False
        config.review.code_context = False

        primary = MagicMock(spec=LLMProvider)
        primary.review = AsyncMock(return_value=_review_response([_raw(9, "Solo")]))
        primary.complete = AsyncMock(return_value="")
        primary.count_tokens = MagicMock(return_value=100)
        primary.usage = {"total_tokens": 100}

        engine = ReviewEngine(config=config, llm=primary)
        assert engine.secondary_llm is None
        result = await engine.review_diff(sample_diff_text)
        assert {c.title for c in result.comments} == {"Solo"}
        assert primary.review.await_count == 1

    @pytest.mark.asyncio
    async def test_secondary_cost_aggregated(self, sample_diff_text: str):
        config = MiraConfig()
        config.llm.secondary_review_model = "openai/gpt-4o"
        config.review.walkthrough = False
        config.review.security_pass = False
        config.review.self_critique = False
        config.review.include_summary = False
        config.review.code_context = False

        primary = MagicMock(spec=LLMProvider)
        primary.review = AsyncMock(return_value=_review_response([_raw(9, "P")]))
        primary.complete = AsyncMock(return_value="")
        primary.count_tokens = MagicMock(return_value=100)
        primary.usage = {"total_tokens": 100, "cost_usd": 0.05}

        secondary = MagicMock(spec=LLMProvider)
        secondary.review = AsyncMock(return_value=_review_response([_raw(20, "S")]))
        secondary.complete = AsyncMock(return_value="")
        secondary.count_tokens = MagicMock(return_value=100)
        secondary.usage = {"total_tokens": 100, "cost_usd": 0.07}

        engine = ReviewEngine(config=config, llm=primary, secondary_llm=secondary)
        result = await engine.review_diff(sample_diff_text)
        # 0.05 (primary) + 0.07 (secondary) = 0.12
        assert result.cost_usd == pytest.approx(0.12)

    @pytest.mark.asyncio
    async def test_max_comments_doubled_when_secondary_set(self, sample_diff_text: str):
        config = MiraConfig()
        config.llm.secondary_review_model = "openai/gpt-4o"
        config.filter.max_comments = 2
        config.review.walkthrough = False
        config.review.security_pass = False
        config.review.self_critique = False
        config.review.include_summary = False
        config.review.code_context = False

        primary = MagicMock(spec=LLMProvider)
        primary.review = AsyncMock(
            return_value=_review_response(
                [
                    _raw(3, "P1", severity="nitpick"),
                    _raw(7, "P2", severity="nitpick"),
                    _raw(11, "P3", severity="nitpick"),
                ]
            )
        )
        primary.complete = AsyncMock(return_value="")
        primary.count_tokens = MagicMock(return_value=100)
        primary.usage = {"total_tokens": 100}

        secondary = MagicMock(spec=LLMProvider)
        secondary.review = AsyncMock(
            return_value=_review_response(
                [
                    _raw(15, "S1", severity="nitpick"),
                    _raw(19, "S2", severity="nitpick"),
                    _raw(22, "S3", severity="nitpick"),
                ]
            )
        )
        secondary.complete = AsyncMock(return_value="")
        secondary.count_tokens = MagicMock(return_value=100)
        secondary.usage = {"total_tokens": 100}

        engine = ReviewEngine(config=config, llm=primary, secondary_llm=secondary)
        result = await engine.review_diff(sample_diff_text)
        # cap=2, doubled=4. 6 unique findings across 2 models → 4 kept.
        assert len(result.comments) == 4
