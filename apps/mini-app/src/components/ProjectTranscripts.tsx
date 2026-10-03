import { Captions, ChevronDown, ChevronRight } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router";
import type { AssetOut } from "../api/client";
import type { JobProgress } from "../hooks/useProjectEvents";
import { formatDuration, pct } from "../services/format";
import { TRANSCRIPT_STATUS_LABEL } from "../strings";
import { haptic } from "../telegram";
import { TranscriptView, languageName } from "./TranscriptView";
import { Badge, Card, EmptyState, ProgressBar } from "./ui";

const TONE = { queued: "neutral", running: "run", done: "ok", failed: "err" } as const;

/** The Transcript tab: every file with speech, its state and (on tap) its text. */
export function ProjectTranscripts({
  projectId,
  assets,
  speech,
}: {
  projectId: string;
  assets: AssetOut[];
  speech: Record<string, JobProgress>;
}) {
  const navigate = useNavigate();
  const [open, setOpen] = useState<string | null>(null);
  const withSpeech = assets.filter((a) => a.transcript_status || (a.status === "ready" && a.has_audio));
  if (!withSpeech.length) {
    return (
      <Card>
        <EmptyState icon={<Captions className="size-6" />} title="Hali transkript yo'q">
          Ovozli video yoki audio yuklang — tahlildan keyin nutq avtomatik so'zma-so'z matnga o'giriladi.
        </EmptyState>
      </Card>
    );
  }
  return (
    <div className="space-y-3">
      {withSpeech.map((a) => {
        const status = a.transcript_status;
        const expanded = open === a.id && status === "done";
        const live = speech[a.id];
        return (
          <Card key={a.id}>
            <button
              type="button"
              className="flex w-full items-center gap-3 px-4 py-3 text-left"
              onClick={() => {
                haptic.select();
                if (status === "done") setOpen(expanded ? null : a.id);
                else navigate(`/p/${projectId}/a/${a.id}`);
              }}
            >
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium">{a.original_filename}</p>
                <p className="tabular mt-0.5 text-xs text-faint">
                  {[a.duration_sec ? formatDuration(a.duration_sec) : null, status === "done" ? languageName(a.transcript_language) : null]
                    .filter(Boolean)
                    .join(" · ")}
                </p>
              </div>
              <Badge tone={status ? TONE[status] : "neutral"}>
                {status === "running" && live ? `${TRANSCRIPT_STATUS_LABEL.running} ${pct(live.progress)}` : status ? TRANSCRIPT_STATUS_LABEL[status] : "boshlanmagan"}
              </Badge>
              {status === "done" ? (
                <ChevronDown className={`size-4 shrink-0 text-faint transition-transform ${expanded ? "rotate-180" : ""}`} aria-hidden />
              ) : (
                <ChevronRight className="size-4 shrink-0 text-faint" aria-hidden />
              )}
            </button>
            {status === "running" && <ProgressBar value={live?.progress ?? 0} tone="run" className="mx-4 mb-3" />}
            {expanded && (
              <div className="border-t border-line">
                <TranscriptView
                  assetId={a.id}
                  version={a.transcript_finished_at}
                  onSeek={(t) => navigate(`/p/${projectId}/a/${a.id}?t=${t.toFixed(2)}`)}
                />
              </div>
            )}
          </Card>
        );
      })}
    </div>
  );
}
