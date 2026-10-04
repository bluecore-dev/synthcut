import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Clapperboard, Eye, History } from "lucide-react";
import { api, unwrap } from "../api/client";
import type { JobProgress } from "../hooks/useProjectEvents";
import { formatDuration, formatRelative } from "../services/format";
import { PLAN_SOURCE_LABEL } from "../strings";
import { haptic } from "../telegram";
import { RenderCard } from "./RenderCard";
import { Badge, Button, Card, EmptyState, ErrorNote, SectionLabel, Skeleton } from "./ui";

/** Every plan version, newest first; any of them can be viewed or rendered again. */
export function Versions({ projectId, onOpen }: { projectId: string; onOpen: (version: number) => void }) {
  const qc = useQueryClient();
  const plans = useQuery({
    queryKey: ["plans", projectId],
    queryFn: () => unwrap(api.GET("/api/v1/projects/{project_id}/plans", { params: { path: { project_id: projectId } } })),
  });
  const renders = useQuery({
    queryKey: ["renders", projectId],
    queryFn: () => unwrap(api.GET("/api/v1/projects/{project_id}/renders", { params: { path: { project_id: projectId } } })),
  });
  const render = useMutation({
    mutationFn: (version: number) =>
      unwrap(api.POST("/api/v1/projects/{project_id}/plans/{version}/render", { params: { path: { project_id: projectId, version } }, body: { deliver: false, force: false } })),
    onSuccess: () => {
      haptic.success();
      void qc.invalidateQueries({ queryKey: ["renders", projectId] });
      void qc.invalidateQueries({ queryKey: ["edit", projectId] });
    },
    onError: () => haptic.error(),
  });

  if (plans.isPending) return <Skeleton className="h-40" />;
  if (!plans.data?.items.length) {
    return (
      <Card>
        <EmptyState icon={<History className="size-6" />} title="Versiyalar yo'q">
          Har montaj yangi versiya bo'ladi; eskilari o'chmaydi — istalganiga qaytish mumkin.
        </EmptyState>
      </Card>
    );
  }
  const rendered = new Map((renders.data?.items ?? []).map((r) => [r.plan_version, r]));

  return (
    <div>
      <SectionLabel right={<span className="text-xs text-faint">{plans.data.items.length}</span>}>Versiyalar</SectionLabel>
      <Card>
        <ul className="divide-y divide-line">
          {plans.data.items.map((p) => {
            const r = rendered.get(p.version);
            return (
              <li key={p.id} className="space-y-2 px-4 py-3">
                <div className="flex items-center gap-2">
                  <Badge tone="accent">v{p.version}</Badge>
                  <span className="text-[13px] font-semibold">{PLAN_SOURCE_LABEL[p.source]}</span>
                  <span className="ml-auto text-xs text-faint">{formatRelative(p.created_at)}</span>
                </div>
                <p className="tabular text-xs text-faint">
                  {formatDuration(p.duration_sec)} · {p.clip_count} bo'lak
                  {r ? ` · render: ${r.status === "done" ? "tayyor" : r.status === "failed" ? "xato" : "jarayonda"}` : ""}
                </p>
                <div className="flex gap-2">
                  <Button size="sm" variant="ghost" icon={<Eye className="size-4" />} onClick={() => onOpen(p.version)}>
                    Ko'rish
                  </Button>
                  {!r && (
                    <Button size="sm" variant="secondary" icon={<Clapperboard className="size-4" />} loading={render.isPending && render.variables === p.version} onClick={() => render.mutate(p.version)}>
                      Render
                    </Button>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      </Card>
      {render.isError && <ErrorNote>{(render.error as Error).message}</ErrorNote>}
    </div>
  );
}

/** Final renders, newest first. */
export function RenderHistory({ projectId, filename, live }: { projectId: string; filename: string; live: Record<string, JobProgress> }) {
  const renders = useQuery({
    queryKey: ["renders", projectId],
    queryFn: () => unwrap(api.GET("/api/v1/projects/{project_id}/renders", { params: { path: { project_id: projectId } } })),
  });
  if (renders.isPending) return <Skeleton className="h-40" />;
  if (!renders.data?.items.length) {
    return (
      <Card>
        <EmptyState icon={<Clapperboard className="size-6" />} title="Render yo'q">
          Tez montajdan keyin yakuniy video shu yerda saqlanadi.
        </EmptyState>
      </Card>
    );
  }
  return (
    <div className="space-y-3">
      {renders.data.items.map((r) => (
        <Card key={r.id} className="p-4">
          <RenderCard projectId={projectId} render={r} live={live[r.id]} filename={filename} compact />
        </Card>
      ))}
    </div>
  );
}

/** The newest finished render, full size, with its QA report. */
export function Preview({ projectId, filename, live }: { projectId: string; filename: string; live: Record<string, JobProgress> }) {
  const renders = useQuery({
    queryKey: ["renders", projectId],
    queryFn: () => unwrap(api.GET("/api/v1/projects/{project_id}/renders", { params: { path: { project_id: projectId } } })),
  });
  if (renders.isPending) return <Skeleton className="h-72" />;
  const latest = renders.data?.items.find((r) => r.status === "done") ?? renders.data?.items[0];
  if (!latest) {
    return (
      <Card>
        <EmptyState icon={<Eye className="size-6" />} title="Ko'rish uchun video yo'q">
          Tez montaj tugagach video shu yerda ochiladi.
        </EmptyState>
      </Card>
    );
  }
  return (
    <Card className="p-4">
      <RenderCard projectId={projectId} render={latest} live={live[latest.id]} filename={filename} />
    </Card>
  );
}
