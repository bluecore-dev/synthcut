import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Brain, MessageSquarePlus, Wand2 } from "lucide-react";
import { useState } from "react";
import { api, unwrap, type Schemas } from "../api/client";
import { haptic } from "../telegram";
import { Button, Chip, ErrorNote } from "./ui";

type Code = Schemas["FeedbackOption"]["code"];
type Result = Schemas["FeedbackOut"];

/** Quick corrections on a finished video. Each is a fixed rule on the
 *  remembered Tez montaj settings, so the next cut — this project's or the
 *  next project's — starts from it; a comment is kept for the AI agent. */
export function Feedback({ projectId, renderId }: { projectId: string; renderId: string }) {
  const qc = useQueryClient();
  const preferences = useQuery({ queryKey: ["preferences"], queryFn: () => unwrap(api.GET("/api/v1/preferences/edit")) });
  const [open, setOpen] = useState(false);
  const [codes, setCodes] = useState<Code[]>([]);
  const [comment, setComment] = useState("");
  const [result, setResult] = useState<Result | null>(null);
  const send = useMutation({
    mutationFn: (remake: boolean) =>
      unwrap(
        api.POST("/api/v1/renders/{render_id}/feedback", {
          params: { path: { render_id: renderId } },
          body: { codes, comment: comment.trim() || null, at_sec: null, remake },
        }),
      ),
    onSuccess: (data) => {
      haptic.success();
      setResult(data);
      setCodes([]);
      setComment("");
      for (const key of [["preferences"], ["edit", projectId], ["renders", projectId], ["plans", projectId]]) {
        void qc.invalidateQueries({ queryKey: key });
      }
    },
    onError: () => haptic.error(),
  });
  const toggle = (code: Code) => setCodes((c) => (c.includes(code) ? c.filter((x) => x !== code) : [...c, code]));
  const empty = codes.length === 0 && !comment.trim();

  if (result && !open) {
    return (
      <div className="rounded-xl border border-line bg-s2 p-3 text-[12px]">
        <p className="flex items-center gap-1.5 font-semibold">
          <Brain className="size-3.5 text-accent" aria-hidden /> Eslab qolindi
        </p>
        <ul className="mt-1 space-y-0.5 text-dim">
          {result.changes.length ? result.changes.map((c) => <li key={c.key}>{c.label}</li>) : <li>Izoh saqlandi</li>}
        </ul>
        {result.remake_job_id && <p className="mt-1 text-run">Yangi versiya montaj qilinmoqda</p>}
        <button type="button" className="mt-2 text-xs font-semibold text-accent" onClick={() => { setResult(null); setOpen(true); }}>
          Yana fikr bildirish
        </button>
      </div>
    );
  }
  if (!open) {
    return (
      <button type="button" onClick={() => setOpen(true)} className="flex items-center gap-1.5 text-xs font-semibold text-accent">
        <MessageSquarePlus className="size-3.5" aria-hidden /> Fikr bildirish
      </button>
    );
  }
  return (
    <div className="space-y-2 rounded-xl border border-line bg-s2 p-3">
      <p className="text-[12px] text-dim">Nima yoqmadi? Tanlovingiz keyingi montajlarga ham qo'llanadi.</p>
      <div className="flex flex-wrap gap-2">
        {(preferences.data?.feedback_options ?? []).map((o) => (
          <Chip key={o.code} active={codes.includes(o.code)} onClick={() => toggle(o.code)}>
            {o.label}
          </Chip>
        ))}
      </div>
      <textarea
        value={comment}
        onChange={(e) => setComment(e.target.value.slice(0, 2000))}
        rows={2}
        placeholder="Boshqa izoh (AI agent uchun saqlanadi)"
        className="w-full rounded-xl border border-line bg-s1 px-3 py-2 text-sm outline-none focus:border-accent"
      />
      <div className="grid grid-cols-2 gap-2">
        <Button size="sm" variant="secondary" disabled={empty} loading={send.isPending && send.variables === false} onClick={() => send.mutate(false)}>
          Eslab qolish
        </Button>
        <Button size="sm" variant="primary" icon={<Wand2 className="size-4" />} disabled={codes.length === 0} loading={send.isPending && send.variables === true} onClick={() => send.mutate(true)}>
          Qayta montaj
        </Button>
      </div>
      <button type="button" className="text-xs text-faint" onClick={() => setOpen(false)}>
        Bekor qilish
      </button>
      {send.isError && <ErrorNote>{(send.error as Error).message}</ErrorNote>}
    </div>
  );
}
