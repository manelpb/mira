"""Multi-run ensemble: review the same chunk N times, keep consensus findings.

Variance-driven false positives flicker across runs while real findings
recur, so a majority vote across independent samples filters both noise
and plausibility-bias FPs. Costs N× review-tier tokens; runs fire in
parallel so wall clock stays roughly flat.
"""

from __future__ import annotations

import copy

from mira.core.noise_filter import _is_duplicate
from mira.models import ReviewComment


def merge_ensemble_runs(
    runs: list[list[ReviewComment]],
    min_votes: int | None = None,
) -> list[ReviewComment]:
    """Cluster comments across runs and keep findings seen in >= min_votes runs.

    ``min_votes`` defaults to a strict majority of the runs. The kept
    representative is the cluster's highest-confidence member, with its
    confidence replaced by the cluster mean — recurrence strength doubles
    as a calibration signal.
    """
    if not runs:
        return []
    if len(runs) == 1:
        return list(runs[0])
    if min_votes is None:
        min_votes = len(runs) // 2 + 1

    clusters: list[list[tuple[int, ReviewComment]]] = []
    for run_idx, run in enumerate(runs):
        for comment in run:
            for cluster in clusters:
                if any(_is_duplicate(comment, other) for _, other in cluster):
                    cluster.append((run_idx, comment))
                    break
            else:
                clusters.append([(run_idx, comment)])

    merged: list[ReviewComment] = []
    for cluster in clusters:
        votes = len({run_idx for run_idx, _ in cluster})
        if votes < min_votes:
            continue
        rep = copy.copy(max(cluster, key=lambda pair: pair[1].confidence)[1])
        rep.confidence = round(sum(c.confidence for _, c in cluster) / len(cluster), 3)
        merged.append(rep)
    return merged


def cross_model_merge(
    primary: list[ReviewComment],
    secondary: list[ReviewComment],
    line_tolerance: int = 3,
) -> tuple[list[ReviewComment], dict]:
    """Union with cross-model confidence boost.

    Two findings match when (path, |line_a - line_b| <= tolerance, category)
    are all equal. Matched findings: keep the higher-severity representative,
    set confidence = mean(primary.conf, secondary.conf). Unmatched findings:
    kept as-is with their original confidence. Each kept comment is tagged
    with ``_source_model`` reflecting which model produced the kept
    representative ("primary" or "secondary").

    Returns ``(merged, audit)`` where ``audit`` is
    ``{"matched": int, "primary_only": int, "secondary_only": int}``.
    """
    audit = {"matched": 0, "primary_only": 0, "secondary_only": 0}
    if not primary and not secondary:
        return [], audit
    if not secondary:
        tagged: list[ReviewComment] = []
        for c in primary:
            k = copy.copy(c)
            k._source_model = "primary"
            tagged.append(k)
        return tagged, {**audit, "primary_only": len(primary)}
    if not primary:
        tagged = []
        for c in secondary:
            k = copy.copy(c)
            k._source_model = "secondary"
            tagged.append(k)
        return tagged, {**audit, "secondary_only": len(secondary)}

    # Greedy matching: for each secondary finding, find the first primary
    # finding at the same (path, line±tol, category). O(n*m); n and m are
    # both per-chunk comment counts (typically <20) so this is fine.
    matched_secondary: set[int] = set()
    merged: list[ReviewComment] = []
    for p in primary:
        match_idx = None
        for j, s in enumerate(secondary):
            if j in matched_secondary:
                continue
            if p.path != s.path:
                continue
            if p.category != s.category:
                continue
            if abs(p.line - s.line) > line_tolerance:
                continue
            match_idx = j
            break
        if match_idx is None:
            kept = copy.copy(p)
            kept._source_model = "primary"
            merged.append(kept)
            audit["primary_only"] += 1
        else:
            s = secondary[match_idx]
            matched_secondary.add(match_idx)
            # Keep the higher-severity representative; if equal, keep primary.
            base = p if p.severity >= s.severity else s
            kept = copy.copy(base)
            kept.confidence = round((p.confidence + s.confidence) / 2, 3)
            kept._source_model = "primary" if base is p else "secondary"
            merged.append(kept)
            audit["matched"] += 1

    for j, s in enumerate(secondary):
        if j in matched_secondary:
            continue
        kept = copy.copy(s)
        kept._source_model = "secondary"
        merged.append(kept)
        audit["secondary_only"] += 1

    return merged, audit
