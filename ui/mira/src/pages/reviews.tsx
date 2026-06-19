import {
  ChevronLeft,
  ChevronRight,
  ExternalLink,
  Loader2,
} from "lucide-react"
import { useEffect, useState } from "react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { api, type PaginatedReviewEvents, type PaginatedReviews } from "@/lib/api"
import { useDocumentTitle } from "@/lib/hooks"

const PER_PAGE = 20

const STATUS_MAP: Record<
  string,
  { label: string; variant: "default" | "secondary" | "destructive" | "outline" }
> = {
  reviewing: { label: "Reviewing", variant: "default" },
  completed: { label: "Completed", variant: "secondary" },
  failed: { label: "Failed", variant: "destructive" },
}

function ago(ts: number): string {
  const sec = Math.floor((Date.now() / 1000 - ts))
  if (sec < 60) return `${sec}s ago`
  const min = Math.floor(sec / 60)
  if (min < 60) return `${min}m ago`
  const hr = Math.floor(min / 60)
  return `${hr}h ago`
}

export function RunningReviewsPage() {
  useDocumentTitle("Reviews")
  const [data, setData] = useState<PaginatedReviews | null>(null)
  const [loading, setLoading] = useState(true)
  const [page, setPage] = useState(0)
  const [recentEvents, setRecentEvents] = useState<PaginatedReviewEvents | null>(null)
  const [eventsPage, setEventsPage] = useState(0)

  const pageItems = data?.items ?? []
  const total = data?.total ?? 0
  const hasActive = pageItems.some((r) => r.status === "reviewing")

  useEffect(() => {
    const load = () => {
      const offset = page * PER_PAGE
      api.getRunningReviews({ limit: PER_PAGE, offset }).then(setData).finally(() => setLoading(false))
    }
    load()
    const interval = setInterval(load, hasActive ? 3000 : 15000)
    return () => clearInterval(interval)
  }, [hasActive, page])

  useEffect(() => {
    api.getRecentReviewEvents({ limit: PER_PAGE, offset: eventsPage * PER_PAGE }).then(setRecentEvents)
  }, [eventsPage])

  const totalPages = Math.ceil(total / PER_PAGE)

  return (
    <div className="space-y-6 p-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Reviews</h1>
        <p className="text-sm text-muted-foreground">
          Active and recent PR reviews
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>
            {loading ? (
              <Loader2 className="h-5 w-5 animate-spin" />
            ) : (
              total
            )}
          </CardTitle>
          <CardDescription>
            {total === 1 ? "review" : "reviews"} tracked
            {hasActive && " — polling live"}
          </CardDescription>
        </CardHeader>
        <CardContent>
          {total === 0 ? (
            <p className="text-sm text-muted-foreground">
              No reviews have been tracked yet.
            </p>
          ) : (
            <>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>PR</TableHead>
                    <TableHead>Title</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Started</TableHead>
                    <TableHead>Duration</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {pageItems.map((r) => {
                    const info = STATUS_MAP[r.status] ?? {
                      label: r.status,
                      variant: "outline" as const,
                    }
                    const dur =
                      r.status !== "reviewing" && r.finished_at > 0
                        ? `${Math.round(r.finished_at - r.started_at)}s`
                        : "—"

                    return (
                      <TableRow key={`${r.repo}#${r.pr_number}`}>
                        <TableCell className="font-medium">
                          <a
                            href={r.pr_url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="inline-flex items-center gap-1 underline-offset-2 hover:underline"
                          >
                            {r.repo}#{r.pr_number}
                            <ExternalLink className="h-3 w-3 text-muted-foreground" />
                          </a>
                        </TableCell>
                        <TableCell className="max-w-md truncate text-muted-foreground">
                          {r.pr_title || "—"}
                        </TableCell>
                        <TableCell>
                          <Badge variant={info.variant}>{info.label}</Badge>
                        </TableCell>
                        <TableCell className="text-muted-foreground tabular-nums">
                          {ago(r.started_at)}
                        </TableCell>
                        <TableCell className="tabular-nums">{dur}</TableCell>
                      </TableRow>
                    )
                  })}
                </TableBody>
              </Table>

              {totalPages > 1 && (
                <div className="mt-4 flex items-center justify-center gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={page === 0}
                    onClick={() => setPage(page - 1)}
                  >
                    <ChevronLeft className="h-4 w-4" />
                  </Button>
                  <span className="text-sm text-muted-foreground tabular-nums">
                    {page + 1} / {totalPages}
                  </span>
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={page >= totalPages - 1}
                    onClick={() => setPage(page + 1)}
                  >
                    <ChevronRight className="h-4 w-4" />
                  </Button>
                </div>
              )}
            </>
          )}
        </CardContent>
      </Card>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle>
              {recentEvents === null ? (
                <Loader2 className="h-5 w-5 animate-spin" />
              ) : (
                recentEvents.total
              )}
            </CardTitle>
            <CardDescription>
              recent review events
            </CardDescription>
          </CardHeader>
          <CardContent>
            {recentEvents === null || recentEvents.items.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                No historical review events yet.
              </p>
            ) : (
              <>
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Repo</TableHead>
                      <TableHead>PR</TableHead>
                      <TableHead>Title</TableHead>
                      <TableHead>Tokens</TableHead>
                      <TableHead>Cost</TableHead>
                      <TableHead>Comments</TableHead>
                      <TableHead>Time</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {recentEvents.items.map((e) => (
                      <TableRow key={`${e.pr_url}#${e.id}`}>
                        <TableCell className="font-medium text-muted-foreground">
                          {extractRepo(e.pr_url)}
                        </TableCell>
                        <TableCell className="font-medium">
                          <a
                            href={e.pr_url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="inline-flex items-center gap-1 underline-offset-2 hover:underline"
                          >
                            #{e.pr_number}
                            <ExternalLink className="h-3 w-3 text-muted-foreground" />
                          </a>
                        </TableCell>
                        <TableCell className="max-w-sm truncate text-muted-foreground">
                          {e.pr_title || "—"}
                        </TableCell>
                        <TableCell className="tabular-nums text-muted-foreground">
                          {e.tokens_used.toLocaleString()}
                        </TableCell>
                        <TableCell className="tabular-nums font-medium">
                          ${e.cost_usd.toFixed(4)}
                        </TableCell>
                        <TableCell className="tabular-nums text-muted-foreground">
                          {e.comments_posted}
                        </TableCell>
                        <TableCell className="tabular-nums text-muted-foreground">
                          {ago(e.created_at)}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>

                {recentEvents && Math.ceil(recentEvents.total / PER_PAGE) > 1 && (
                  <div className="mt-4 flex items-center justify-center gap-2">
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={eventsPage === 0}
                      onClick={() => setEventsPage(eventsPage - 1)}
                    >
                      <ChevronLeft className="h-4 w-4" />
                    </Button>
                    <span className="text-sm text-muted-foreground tabular-nums">
                      {eventsPage + 1} / {Math.ceil(recentEvents.total / PER_PAGE)}
                    </span>
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={eventsPage >= Math.ceil(recentEvents.total / PER_PAGE) - 1}
                      onClick={() => setEventsPage(eventsPage + 1)}
                    >
                      <ChevronRight className="h-4 w-4" />
                    </Button>
                  </div>
                )}
              </>
            )}
          </CardContent>
        </Card>

        <CostBreakdownCard />
      </div>
    </div>
  )
}

function CostBreakdownCard() {
  const [weekly, setWeekly] = useState<{ date: string; cost_usd: number }[] | null>(null)
  const [monthly, setMonthly] = useState<{ date: string; cost_usd: number }[] | null>(null)

  useEffect(() => {
    api.getTimeseries("week").then((d) => setWeekly(d))
    api.getTimeseries("month").then((d) => setMonthly(d))
  }, [])

  const totalWeekly = weekly?.reduce((s, p) => s + p.cost_usd, 0) ?? 0
  const totalMonthly = monthly?.reduce((s, p) => s + p.cost_usd, 0) ?? 0

  return (
    <Card>
      <CardHeader>
        <CardTitle>Cost Breakdown</CardTitle>
        <CardDescription>
          Aggregate cost by week and month
        </CardDescription>
      </CardHeader>
      <CardContent>
        {!weekly && !monthly ? (
          <p className="text-sm text-muted-foreground">Loading...</p>
        ) : (
          <div className="space-y-6">
            <div>
              <h3 className="mb-2 text-sm font-medium text-muted-foreground">
                By Week (${totalWeekly.toFixed(4)} total)
              </h3>
              {weekly && weekly.length > 0 ? (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Week</TableHead>
                      <TableHead className="text-right">Cost</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {weekly.map((p) => (
                      <TableRow key={p.date}>
                        <TableCell className="tabular-nums text-muted-foreground">
                          {p.date}
                        </TableCell>
                        <TableCell className="tabular-nums text-right font-medium">
                          ${p.cost_usd.toFixed(4)}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              ) : (
                <p className="text-sm text-muted-foreground">No data</p>
              )}
            </div>
            <div>
              <h3 className="mb-2 text-sm font-medium text-muted-foreground">
                By Month (${totalMonthly.toFixed(4)} total)
              </h3>
              {monthly && monthly.length > 0 ? (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Month</TableHead>
                      <TableHead className="text-right">Cost</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {monthly.map((p) => (
                      <TableRow key={p.date}>
                        <TableCell className="tabular-nums text-muted-foreground">
                          {p.date}
                        </TableCell>
                        <TableCell className="tabular-nums text-right font-medium">
                          ${p.cost_usd.toFixed(4)}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              ) : (
                <p className="text-sm text-muted-foreground">No data</p>
              )}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  )
}

function extractRepo(prUrl: string): string {
  try {
    const u = new URL(prUrl)
    const parts = u.pathname.split("/").filter(Boolean)
    if (parts[0] === "github.com") parts.shift()
    return parts.slice(0, 2).join("/") || "?"
  } catch {
    return "?"
  }
}
