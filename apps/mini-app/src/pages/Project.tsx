import { useQuery } from "@tanstack/react-query";
import { Bot, CircleDollarSign, Lock, Radio } from "lucide-react";
import { useSearchParams, useParams } from "react-router";
import { api, unwrap, type ProjectOut } from "../api/client";
import { ActivityLog } from "../components/ActivityLog";
import { AssetList } from "../components/AssetList";
import { StageList } from "../components/StageList";
import { UploadPanel } from "../components/UploadPanel";
import { Badge, Card, EmptyState, ErrorNote, ProgressBar, SectionLabel, Skeleton, cx } from "../components/ui";
import { useBackButton } from "../hooks/useBackButton";
import { presetBadge, usePresets } from "../hooks/usePresets";
import { useProjectEvents } from "../hooks/useProjectEvents";
import { formatBytes, formatClock, pct } from "../services/format";
import { MODE_LABEL, PROJECT_TABS, type ProjectTab } from "../strings";
import { haptic } from "../telegram";

const LOCKED_COPY: Partial<Record<ProjectTab, string>> = {
  analysis: "Har bir kadr tahlili: kompozitsiya, fokus, ekspozitsiya, harakat, foydalanish bahosi.",
  transcript: "Whisper bilan so'zma-so'z transkript, pauzalar va urg'ular.",
  timeline: "Director va Editor tuzgan EditPlan: treklar, kesimlar, o'tishlar.",
  decisions: "Agentlar qaysi qarorni nima uchun qabul qilgani.",
  preview: "Render qilingan preview — tomosha va izoh.",
  versions: "Har katta o'zgarish versiya bo'ladi; istalganiga qaytish mumkin.",
  renders: "Final renderlar tarixi va yuklab olish.",
};

function Overview({ project, events, onAll }: { project: ProjectOut; events: ReturnType<typeof useProjectEvents>["events"]; onAll: () => void }) {
  return (
    <div className="space-y-5">
      <Card className="p-4">
        <div className="flex items-end justify-between">
          <div>
            <p className="label">Progress</p>
            <p className="tabular mt-1 text-3xl font-bold">{pct(project.progress)}</p>
          </div>
          <div className="text-right text-xs text-faint">
            <p className="tabular">
              {project.asset_count} ta fayl · {formatBytes(project.total_bytes)}
            </p>
          </div>
        </div>
        <ProgressBar value={project.progress} className="mt-3" />
        <div className="mt-4 grid grid-cols-2 gap-3">
          <div className="rounded-xl border border-line bg-s2 p-3">
            <p className="label flex items-center gap-1.5">
              <Bot className="size-3.5" aria-hidden /> Joriy agent
            </p>
            <p className="mt-1 text-sm font-semibold">{project.current_agent ?? "—"}</p>
            {!project.current_agent && <p className="text-[11px] text-faint">Agentlar Phase 6 dan</p>}
          </div>
          <div className="rounded-xl border border-line bg-s2 p-3">
            <p className="label flex items-center gap-1.5">
              <CircleDollarSign className="size-3.5" aria-hidden /> AI xarajati
            </p>
            <p className="tabular mt-1 text-sm font-semibold">${project.cost_usd.toFixed(2)}</p>
            <p className="text-[11px] text-faint">model × token bo'yicha</p>
          </div>
        </div>
      </Card>

      <div>
        <SectionLabel>Pipeline</SectionLabel>
        <Card>
          <StageList stages={project.stages} />
        </Card>
      </div>

      <div>
        <SectionLabel
          right={
            <button type="button" className="text-xs font-semibold text-accent" onClick={onAll}>
              Barchasi
            </button>
          }
        >
          Faoliyat
        </SectionLabel>
        <Card>
          <ActivityLog events={events} limit={8} />
        </Card>
      </div>
    </div>
  );
}

function Logs({ projectId, events }: { projectId: string; events: ReturnType<typeof useProjectEvents>["events"] }) {
  const jobs = useQuery({
    queryKey: ["jobs", projectId],
    queryFn: () => unwrap(api.GET("/api/v1/projects/{project_id}/jobs", { params: { path: { project_id: projectId } } })),
  });
  return (
    <div className="space-y-5">
      <div>
        <SectionLabel>Jobs</SectionLabel>
        <Card>
          {jobs.data?.items.length ? (
            <ul className="divide-y divide-line">
              {jobs.data.items.map((j) => (
                <li key={j.id} className="px-4 py-2.5 text-[13px]">
                  <div className="flex items-center gap-2">
                    <span className="min-w-0 flex-1 truncate font-mono text-dim">{j.kind}</span>
                    <Badge tone={j.status === "succeeded" ? "ok" : j.status === "running" ? "run" : j.status === "dead" ? "err" : j.status === "queued" ? "warn" : "neutral"}>
                      {j.status}
                    </Badge>
                  </div>
                  <p className="tabular mt-0.5 text-xs text-faint">
                    {formatClock(j.created_at)} · {j.queue} · urinish {j.attempts}/{j.max_attempts}
                    {j.error ? ` · ${String((j.error as { message?: string }).message ?? "")}` : ""}
                  </p>
                </li>
              ))}
            </ul>
          ) : (
            <p className="px-4 py-6 text-center text-sm text-faint">Hali job yo'q</p>
          )}
        </Card>
      </div>
      <div>
        <SectionLabel>Event log</SectionLabel>
        <Card>
          <ActivityLog events={events} />
        </Card>
      </div>
    </div>
  );
}

export function Project() {
  useBackButton("/");
  const { id = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const tab = (params.get("tab") ?? "overview") as ProjectTab;
  const project = useQuery({
    queryKey: ["project", id],
    queryFn: () => unwrap(api.GET("/api/v1/projects/{project_id}", { params: { path: { project_id: id } } })),
  });
  const assets = useQuery({
    queryKey: ["assets", id],
    queryFn: () => unwrap(api.GET("/api/v1/projects/{project_id}/assets", { params: { path: { project_id: id } } })),
  });
  const { events, remoteUploads, stream } = useProjectEvents(id);
  const presets = usePresets();

  const setTab = (next: ProjectTab) => {
    haptic.select();
    setParams({ tab: next }, { replace: true });
  };

  if (project.isPending) {
    return (
      <div className="mx-auto max-w-xl space-y-3 px-4 pt-4">
        <Skeleton className="h-16" />
        <Skeleton className="h-40" />
        <Skeleton className="h-72" />
      </div>
    );
  }
  if (project.isError) {
    return (
      <div className="mx-auto max-w-xl px-4 pt-6">
        <ErrorNote>{(project.error as Error).message}</ErrorNote>
      </div>
    );
  }
  const p = project.data;
  const archived = p.status === "archived";
  // The server says which stages exist yet; tabs follow the same phase line.
  const builtPhase = Math.max(0, ...p.stages.filter((s) => s.available).map((s) => s.phase));

  return (
    <div className="mx-auto max-w-xl pb-10">
      <header className="px-4 pt-4">
        <div className="flex items-center gap-2">
          <h1 className="min-w-0 flex-1 truncate text-xl font-bold">{p.name}</h1>
          <span
            className={cx("inline-flex items-center gap-1 text-[11px] font-semibold", stream === "live" ? "text-ok" : "text-faint")}
            title="Real-time"
          >
            <Radio className={cx("size-3.5", stream === "live" && "pulse")} aria-hidden />
            {stream === "live" ? "LIVE" : "…"}
          </span>
        </div>
        <div className="mt-2 flex flex-wrap gap-1.5">
          {presetBadge(presets.byId.get(p.preset)) && <Badge tone="accent">{presetBadge(presets.byId.get(p.preset))}</Badge>}
          <Badge>{p.fps} fps</Badge>
          <Badge>{MODE_LABEL[p.mode].title}</Badge>
          {p.target_duration_sec && <Badge>{p.target_duration_sec < 60 ? `${p.target_duration_sec}s` : `${Math.round(p.target_duration_sec / 60)} daq`}</Badge>}
          {archived && <Badge tone="warn">arxiv</Badge>}
        </div>
      </header>

      <nav className="no-scrollbar sticky top-0 z-10 mt-4 flex gap-1 overflow-x-auto border-b border-line bg-bg/95 px-3 backdrop-blur">
        {PROJECT_TABS.map((t) => {
          const locked = t.phase > builtPhase;
          return (
            <button
              type="button"
              key={t.id}
              onClick={() => setTab(t.id)}
              className={cx(
                "relative flex shrink-0 items-center gap-1 px-2.5 py-3 text-[13px] font-semibold",
                tab === t.id ? "text-fg" : locked ? "text-faint" : "text-dim",
              )}
            >
              {locked && <Lock className="size-3" aria-hidden />}
              {t.label}
              {tab === t.id && <span className="absolute inset-x-2 bottom-0 h-0.5 rounded-full bg-accent" />}
            </button>
          );
        })}
      </nav>

      <main className="px-4 pt-4">
        {tab === "overview" && <Overview project={p} events={events} onAll={() => setTab("logs")} />}
        {tab === "assets" && (
          <div className="space-y-5">
            <UploadPanel projectId={id} disabled={archived} />
            <div>
              <SectionLabel right={<span className="text-xs text-faint">{assets.data?.items.length ?? 0}</span>}>Assets</SectionLabel>
              <Card>
                {assets.isPending ? (
                  <Skeleton className="m-3 h-14" />
                ) : (
                  <AssetList projectId={id} assets={assets.data?.items ?? []} remote={remoteUploads} />
                )}
              </Card>
            </div>
          </div>
        )}
        {tab === "logs" && <Logs projectId={id} events={events} />}
        {LOCKED_COPY[tab] && (
          <Card>
            <EmptyState icon={<Lock className="size-6" />} title={`${PROJECT_TABS.find((t) => t.id === tab)?.label} — Phase ${PROJECT_TABS.find((t) => t.id === tab)?.phase}`}>
              {LOCKED_COPY[tab]}
            </EmptyState>
          </Card>
        )}
      </main>
    </div>
  );
}
