import { useQuery } from "@tanstack/react-query";
import { Clapperboard } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router";
import { api, unwrap, type ClipOut } from "../api/client";
import { pct } from "../services/format";
import { CLIP_FLAG_LABEL } from "../strings";
import { ClipCard } from "./ClipCard";
import { Card, Chip, EmptyState, ErrorNote, SectionLabel, Skeleton } from "./ui";

type Filter = "all" | "good" | "issues";
const FILTERS: { id: Filter; label: string }[] = [
  { id: "all", label: "Hammasi" },
  { id: "good", label: "Yaroqli" },
  { id: "issues", label: "Muammoli" },
];
const GOOD = 0.75;
const isIssue = (c: ClipOut) => c.usable_score < 0.5 || c.flags.some((f) => f !== "duplicate");

/** The Analysis tab: every analysed shot of the project — the material the Director will choose from. */
export function ProjectClips({ projectId }: { projectId: string }) {
  const navigate = useNavigate();
  const [filter, setFilter] = useState<Filter>("all");
  const q = useQuery({
    queryKey: ["clips", projectId],
    queryFn: () => unwrap(api.GET("/api/v1/projects/{project_id}/clips", { params: { path: { project_id: projectId } } })),
    staleTime: 60_000,
  });
  if (q.isPending) return <Skeleton className="h-64" />;
  if (q.isError) return <ErrorNote>{(q.error as Error).message}</ErrorNote>;
  const clips = q.data.items;
  if (!clips.length) {
    return (
      <Card>
        <EmptyState icon={<Clapperboard className="size-6" />} title="Hali tahlil qilingan kadr yo'q">
          Video yuklang — tahlildan keyin har bir kadr baholanadi: plan, kamera harakati, aniqlik, yorug'lik, nutq, takrorlar.
        </EmptyState>
      </Card>
    );
  }
  const shown = clips.filter((c) => (filter === "good" ? c.usable_score >= GOOD : filter === "issues" ? isIssue(c) : true));
  const avg = clips.reduce((s, c) => s + c.usable_score, 0) / clips.length;
  const flagCounts = new Map<string, number>();
  clips.forEach((c) => c.flags.forEach((f) => flagCounts.set(f, (flagCounts.get(f) ?? 0) + 1)));
  const totalSeconds = clips.filter((c) => c.usable_score >= GOOD).reduce((s, c) => s + c.duration, 0);

  return (
    <div className="space-y-4">
      <Card className="p-4">
        <div className="flex items-end justify-between">
          <div>
            <p className="text-2xl font-bold">{clips.length}</p>
            <p className="text-xs text-faint">kadr</p>
          </div>
          <div className="text-right">
            <p className="text-2xl font-bold">{pct(avg)}</p>
            <p className="text-xs text-faint">o'rtacha yaroqlilik</p>
          </div>
        </div>
        <p className="mt-3 text-[13px] text-dim">
          Yaroqli material: {Math.round(totalSeconds)} s
          {flagCounts.size > 0 && ` · ${[...flagCounts].map(([f, n]) => `${n} ${CLIP_FLAG_LABEL[f as ClipOut["flags"][number]]}`).join(", ")}`}
        </p>
        <p className="mt-2 text-[11px] text-faint">Baholar o'lchovlardan (aniqlik, yorug'lik, kamera, yuzlar, nutq). Mazmun tavsifi AI tahlilchi ulanganda qo'shiladi.</p>
      </Card>
      <div className="flex gap-2">
        {FILTERS.map((f) => (
          <Chip key={f.id} active={filter === f.id} onClick={() => setFilter(f.id)}>
            {f.label}
          </Chip>
        ))}
      </div>
      <div>
        <SectionLabel right={<span className="text-xs text-faint">{shown.length}</span>}>Kadrlar</SectionLabel>
        <Card className="divide-y divide-line">
          {shown.map((c) => (
            <ClipCard key={c.clip_id} clip={c} showAsset onOpen={() => navigate(`/p/${projectId}/a/${c.asset_id}?t=${c.start.toFixed(2)}`)} />
          ))}
          {!shown.length && <p className="px-4 py-6 text-center text-sm text-faint">Bu filtrga mos kadr yo'q.</p>}
        </Card>
      </div>
    </div>
  );
}
