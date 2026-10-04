import { useQuery } from "@tanstack/react-query";
import { Film, Type } from "lucide-react";
import { api, unwrap } from "../api/client";
import { formatDuration } from "../services/format";
import { CAPTION_STYLE_LABEL, PLAN_SOURCE_LABEL } from "../strings";
import { Badge, Card, EmptyState, SectionLabel, Skeleton } from "./ui";

const COLOURS = ["bg-accent/70", "bg-ok/70", "bg-warn/70", "bg-run/70", "bg-brand/70", "bg-err/60"];

const sec = (t: number) => `${t.toFixed(1)} s`;

/** A plan version: the cut as proportional bars per source file, then every clip and graphic. */
export function TimelineView({ projectId, version }: { projectId: string; version: number | null }) {
  const plans = useQuery({
    queryKey: ["plans", projectId],
    queryFn: () => unwrap(api.GET("/api/v1/projects/{project_id}/plans", { params: { path: { project_id: projectId } } })),
  });
  const chosen = version ?? plans.data?.items[0]?.version ?? null;
  const plan = useQuery({
    queryKey: ["plans", projectId, chosen],
    enabled: chosen != null,
    queryFn: () => unwrap(api.GET("/api/v1/projects/{project_id}/plans/{version}", { params: { path: { project_id: projectId, version: chosen! } } })),
  });

  if (plans.isPending || (chosen != null && plan.isPending)) return <Skeleton className="h-56" />;
  if (chosen == null || !plan.data) {
    return (
      <Card>
        <EmptyState icon={<Film className="size-6" />} title="Hali montaj yo'q">
          Overview'dagi «Tez montaj» tugmasi birinchi versiyani yaratadi.
        </EmptyState>
      </Card>
    );
  }
  const p = plan.data;
  const assets = [...new Set(p.clips.map((c) => c.asset_id))];
  const colour = (id: string) => COLOURS[assets.indexOf(id) % COLOURS.length];
  const total = p.duration_sec || 1;

  return (
    <div className="space-y-5">
      <Card className="space-y-3 p-4">
        <div className="flex flex-wrap items-center gap-1.5">
          <Badge tone="accent">v{p.version}</Badge>
          <Badge>{PLAN_SOURCE_LABEL[p.source]}</Badge>
          <Badge>{formatDuration(p.duration_sec)}</Badge>
          <Badge>
            {p.width}×{p.height} · {p.fps} fps
          </Badge>
          {p.captions && <Badge>{CAPTION_STYLE_LABEL[p.captions as keyof typeof CAPTION_STYLE_LABEL]?.title ?? p.captions}</Badge>}
          {p.loudness_lufs != null && <Badge>{p.loudness_lufs} LUFS</Badge>}
        </div>
        <div className="relative h-9 overflow-hidden rounded-lg bg-s2" role="img" aria-label="Montaj chizig'i">
          {p.clips.map((c) => (
            <div
              key={c.id}
              className={`absolute inset-y-0 border-r border-bg ${colour(c.asset_id)}`}
              style={{ left: `${(c.timeline_start / total) * 100}%`, width: `${((c.timeline_end - c.timeline_start) / total) * 100}%` }}
              title={`${c.asset_name ?? ""} ${sec(c.source_in)}–${sec(c.source_out)}`}
            />
          ))}
        </div>
        {p.graphics.length > 0 && (
          <div className="relative h-4 rounded bg-s2">
            {p.graphics.map((g) => (
              <div
                key={g.id}
                className="absolute inset-y-0 rounded bg-fg/40"
                style={{ left: `${(g.timeline_start / total) * 100}%`, width: `${Math.max(1, ((g.timeline_end - g.timeline_start) / total) * 100)}%` }}
                title={g.component}
              />
            ))}
          </div>
        )}
        {p.notes && <p className="whitespace-pre-line text-[12px] leading-relaxed text-dim">{p.notes}</p>}
      </Card>

      <div>
        <SectionLabel right={<span className="text-xs text-faint">{p.clips.length}</span>}>Bo'laklar</SectionLabel>
        <Card>
          <ul className="divide-y divide-line">
            {p.clips.map((c, i) => (
              <li key={c.id} className="flex items-center gap-3 px-4 py-2.5 text-[13px]">
                <span className={`size-2.5 shrink-0 rounded-full ${colour(c.asset_id)}`} />
                <div className="min-w-0 flex-1">
                  <p className="truncate font-medium">
                    {i + 1}. {c.asset_name ?? c.asset_id.slice(0, 8)}
                  </p>
                  <p className="tabular text-xs text-faint">
                    manba {sec(c.source_in)}–{sec(c.source_out)} → {sec(c.timeline_start)}
                  </p>
                </div>
                <div className="flex shrink-0 gap-1">
                  {c.reframed && <Badge>yuz</Badge>}
                  {c.fill === "blur" && <Badge>fon</Badge>}
                  {c.exposure != null && c.exposure !== 0 && <Badge>{c.exposure > 0 ? "+" : ""}{c.exposure.toFixed(1)} EV</Badge>}
                </div>
              </li>
            ))}
          </ul>
        </Card>
      </div>

      {p.graphics.length > 0 && (
        <div>
          <SectionLabel>Grafika</SectionLabel>
          <Card>
            <ul className="divide-y divide-line">
              {p.graphics.map((g) => (
                <li key={g.id} className="flex items-center gap-3 px-4 py-2.5 text-[13px]">
                  <Type className="size-4 shrink-0 text-accent" aria-hidden />
                  <span className="min-w-0 flex-1 truncate">
                    {g.component}
                    {g.text ? ` — ${g.text}` : ""}
                  </span>
                  <span className="tabular text-xs text-faint">
                    {sec(g.timeline_start)}–{sec(g.timeline_end)}
                  </span>
                </li>
              ))}
            </ul>
          </Card>
        </div>
      )}
    </div>
  );
}
