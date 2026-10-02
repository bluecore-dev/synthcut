import { useQuery } from "@tanstack/react-query";
import { Clapperboard, HardDrive, Plus } from "lucide-react";
import { Link, useNavigate } from "react-router";
import { api, unwrap, type ProjectSummary } from "../api/client";
import { Badge, Button, Card, EmptyState, ErrorNote, ProgressBar, SectionLabel, Skeleton } from "../components/ui";
import { Wordmark } from "../components/Wordmark";
import { presetBadge, usePresets } from "../hooks/usePresets";
import { useUploads } from "../hooks/useUploads";
import { formatBytes, formatRelative, pct } from "../services/format";

function ProjectCard({ p, uploading }: { p: ProjectSummary; uploading: boolean }) {
  const { byId } = usePresets();
  return (
    <Link to={`/p/${p.id}`} className="block active:opacity-80">
      <Card className="p-4">
        <div className="flex items-start gap-3">
          <div className="min-w-0 flex-1">
            <p className="truncate text-[15px] font-semibold">{p.name}</p>
            <p className="tabular mt-0.5 text-xs text-faint">
              {p.asset_count} ta fayl · {formatBytes(p.total_bytes)} · {formatRelative(p.updated_at)}
            </p>
          </div>
          {presetBadge(byId.get(p.preset)) && <Badge tone="accent">{presetBadge(byId.get(p.preset))}</Badge>}
        </div>
        <ProgressBar value={p.progress} className="mt-3" />
        <div className="mt-1.5 flex justify-between text-xs">
          <span className="text-dim">
            {uploading ? "Yuklanmoqda…" : (p.active_stage_label ?? (p.asset_count ? "Kutilmoqda" : "Material yo'q"))}
          </span>
          <span className="tabular text-faint">{pct(p.progress)}</span>
        </div>
      </Card>
    </Link>
  );
}

export function Home() {
  const navigate = useNavigate();
  const projects = useQuery({
    queryKey: ["projects"],
    queryFn: () => unwrap(api.GET("/api/v1/projects")),
  });
  const me = useQuery({ queryKey: ["me"], queryFn: () => unwrap(api.GET("/api/v1/me")), staleTime: 30_000 });
  const activeUploads = new Set(
    useUploads()
      .filter((u) => ["preparing", "verifying", "uploading", "completing"].includes(u.phase))
      .map((u) => u.projectId),
  );
  const limits = me.data?.limits;

  return (
    <div className="mx-auto max-w-xl px-4 pb-28 pt-4">
      <header className="mb-6 flex items-center justify-between">
        <Wordmark />
        {limits && (
          <span className="tabular inline-flex items-center gap-1.5 rounded-lg border border-line bg-s1 px-2 py-1 text-xs text-dim">
            <HardDrive className="size-3.5" aria-hidden />
            {formatBytes(limits.storage_used_bytes + limits.storage_reserved_bytes)} / {formatBytes(limits.storage_quota_bytes, 0)}
          </span>
        )}
      </header>

      <SectionLabel right={projects.data && <span className="text-xs text-faint">{projects.data.items.length}</span>}>
        Loyihalar
      </SectionLabel>

      {projects.isPending && (
        <div className="space-y-3">
          <Skeleton className="h-24" />
          <Skeleton className="h-24" />
        </div>
      )}
      {projects.isError && <ErrorNote>{(projects.error as Error).message}</ErrorNote>}
      {projects.data && projects.data.items.length === 0 && (
        <EmptyState icon={<Clapperboard className="size-6" />} title="Birinchi loyihani yarating">
          Telefon yoki kameradagi xom materialni yuklang — tahlil, montaj, rang, ovoz va render'ni agentlar jamoasi
          bajaradi.
        </EmptyState>
      )}
      <div className="space-y-3">
        {projects.data?.items.map((p) => <ProjectCard key={p.id} p={p} uploading={activeUploads.has(p.id)} />)}
      </div>

      <div className="fixed inset-x-0 bottom-0 border-t border-line bg-bg/90 px-4 pb-[max(12px,env(safe-area-inset-bottom))] pt-3 backdrop-blur">
        <div className="mx-auto max-w-xl">
          <Button variant="primary" size="lg" className="w-full" icon={<Plus className="size-5" />} onClick={() => navigate("/new")}>
            Yangi loyiha
          </Button>
        </div>
      </div>
    </div>
  );
}
