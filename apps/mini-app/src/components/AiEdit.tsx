import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bot, ChevronDown, CircleDollarSign, KeyRound, Sparkles, Wrench } from "lucide-react";
import { useState } from "react";
import { api, unwrap, type ProjectOut } from "../api/client";
import { formatRelative } from "../services/format";
import { haptic } from "../telegram";
import { Badge, Button, Card, EmptyState, ErrorNote, SectionLabel, Skeleton, cx } from "./ui";

const AGENT_TITLE: Record<string, string> = {
  director: "Rejissor",
  editor: "Montajchi",
  motion: "Grafika",
  qa: "Sifat nazorati",
  color: "Rang",
  audio: "Ovoz",
  caption: "Subtitr",
};

const STATUS: Record<string, { label: string; tone: "ok" | "warn" | "err" | "neutral" }> = {
  completed: { label: "tugadi", tone: "ok" },
  max_steps: { label: "qadam chegarasi", tone: "warn" },
  budget_exceeded: { label: "byudjet tugadi", tone: "warn" },
  refused: { label: "rad etdi", tone: "err" },
  truncated: { label: "uzilib qoldi", tone: "warn" },
  failed: { label: "xato", tone: "err" },
};

const IDEAS = ["30 soniyalik reels, kuchli hook bilan", "Dinamik: punch-in va B-roll ko'proq", "Sokin, kinematografik, o'tishlar yumshoq"];

/** AI montaj: the agent team edits on top of the rules draft. */
export function AiEdit({ project }: { project: ProjectOut }) {
  const qc = useQueryClient();
  const status = useQuery({ queryKey: ["ai-status"], queryFn: () => unwrap(api.GET("/api/v1/ai/status")) });
  const [prompt, setPrompt] = useState("");
  const [deliver, setDeliver] = useState(true);
  const run = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST("/api/v1/projects/{project_id}/ai-edit", {
          params: { path: { project_id: project.id } },
          body: { prompt: prompt.trim(), deliver, redraft: false },
        }),
      ),
    onSuccess: (data) => {
      haptic.success();
      qc.setQueryData(["edit", project.id], data);
      void qc.invalidateQueries({ queryKey: ["agent-runs", project.id] });
    },
    onError: () => haptic.error(),
  });
  if (status.isPending) return <Skeleton className="h-24" />;
  const enabled = status.data?.enabled ?? false;

  return (
    <div>
      <SectionLabel right={enabled ? <span className="text-xs text-faint">byudjet ${status.data?.budget_usd}</span> : null}>AI montaj</SectionLabel>
      <Card className="space-y-3 p-4">
        <p className="text-[13px] leading-relaxed text-dim">
          Rejissor hikoyani tuzadi (hook, tartib), montajchi punch-in, B-roll, o'tishlar va tezlikni qo'yadi, grafika agenti sarlavha va chaqiriq qo'shadi, sifat nazorati tekshiradi — keyin render.
        </p>
        {!enabled ? (
          <div className="flex items-start gap-2 rounded-xl border border-line bg-s2 p-3 text-[12px] text-dim">
            <KeyRound className="mt-0.5 size-4 shrink-0 text-warn" aria-hidden />
            AI kaliti (ANTHROPIC_API_KEY) hali ulanmagan. Ulangach shu tugma ishlaydi; hozircha «Tez montaj» qoidalar asosida ishlaydi.
          </div>
        ) : (
          <>
            <textarea
              value={prompt}
              onChange={(e) => setPrompt(e.target.value.slice(0, 2000))}
              rows={3}
              placeholder="Nima qilmoqchisiz? Masalan: 45 soniyalik reels, savol bilan boshlansin, mahsulot kadrlarini B-roll qiling"
              className="w-full rounded-xl border border-line bg-s1 px-3 py-2 text-sm outline-none focus:border-accent"
            />
            <div className="flex flex-wrap gap-1.5">
              {IDEAS.map((idea) => (
                <button key={idea} type="button" onClick={() => setPrompt(idea)} className="rounded-lg border border-line bg-s1 px-2.5 py-1 text-[12px] text-dim active:bg-s2">
                  {idea}
                </button>
              ))}
            </div>
            <label className="flex items-center gap-2 text-[13px]">
              <input type="checkbox" checked={deliver} onChange={(e) => setDeliver(e.target.checked)} />
              Tayyor bo'lgach Telegramga yuborish
            </label>
            <Button className="w-full" size="lg" variant="primary" loading={run.isPending} disabled={project.status === "archived"} icon={<Sparkles className="size-4" />} onClick={() => run.mutate()}>
              AI montaj
            </Button>
          </>
        )}
        {run.isError && <ErrorNote>{(run.error as Error).message}</ErrorNote>}
      </Card>
    </div>
  );
}

/** What each agent decided, did and cost — the AI Decisions tab. */
export function AgentRuns({ projectId }: { projectId: string }) {
  const runs = useQuery({
    queryKey: ["agent-runs", projectId],
    queryFn: () => unwrap(api.GET("/api/v1/projects/{project_id}/agent-runs", { params: { path: { project_id: projectId } } })),
  });
  const [open, setOpen] = useState<string | null>(null);
  if (runs.isPending) return <Skeleton className="h-40" />;
  if (!runs.data?.items.length) {
    return (
      <Card>
        <EmptyState icon={<Bot className="size-6" />} title="AI qarorlari hali yo'q">
          «AI montaj»dan keyin har agent nima qilgani, qaysi versiyani yozgani va qancha turgani shu yerda ko'rinadi.
        </EmptyState>
      </Card>
    );
  }
  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between text-[13px] text-dim">
        <span>{runs.data.items.length} ta agent ishi</span>
        <span className="flex items-center gap-1">
          <CircleDollarSign className="size-3.5" aria-hidden /> jami ${runs.data.total_cost_usd.toFixed(2)}
        </span>
      </div>
      {runs.data.items.map((r) => {
        const st = STATUS[r.status] ?? { label: r.status, tone: "neutral" as const };
        const expanded = open === r.id;
        return (
          <Card key={r.id} className="space-y-2 p-4">
            <div className="flex items-center gap-2">
              <Bot className="size-4 text-accent" aria-hidden />
              <span className="font-semibold">{AGENT_TITLE[r.agent] ?? r.agent}</span>
              <Badge tone={st.tone}>{st.label}</Badge>
              <span className="ml-auto text-xs text-faint">{formatRelative(r.created_at)}</span>
            </div>
            {r.summary && <p className="whitespace-pre-line text-[13px] leading-relaxed">{r.summary}</p>}
            {r.error && <ErrorNote>{r.error}</ErrorNote>}
            <div className="flex flex-wrap gap-1.5">
              {r.versions.map((v) => (
                <Badge key={v} tone="accent">
                  v{v} yozdi
                </Badge>
              ))}
              <Badge>{r.steps} qadam</Badge>
              <Badge>${r.cost_usd.toFixed(3)}</Badge>
              {r.model && <Badge>{r.model.split(":").pop()}</Badge>}
            </div>
            {r.findings.length > 0 && (
              <ul className="space-y-1 text-[12px]">
                {r.findings.map((f, i) => (
                  <li key={i} className={cx(String(f.severity) === "error" ? "text-err" : "text-dim")}>
                    {String(f.severity) === "error" ? "✖" : "•"} {String(f.message)}
                    {f.at != null ? ` (${Number(f.at).toFixed(1)} s)` : ""}
                  </li>
                ))}
              </ul>
            )}
            {r.tool_calls.length > 0 && (
              <button type="button" onClick={() => setOpen(expanded ? null : r.id)} className="flex items-center gap-1 text-xs font-semibold text-accent">
                <Wrench className="size-3.5" aria-hidden /> {r.tool_calls.length} ta tool
                <ChevronDown className={cx("size-3.5 transition-transform", expanded && "rotate-180")} aria-hidden />
              </button>
            )}
            {expanded && (
              <ul className="space-y-1 font-mono text-[11px] text-faint">
                {r.tool_calls.map((c, i) => (
                  <li key={i} className={cx(!c.ok && "text-err")}>
                    {c.tool} {c.ok ? "" : `✖ ${c.error ?? ""}`} · {c.ms} ms
                    <div className="truncate">{c.input}</div>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        );
      })}
    </div>
  );
}
