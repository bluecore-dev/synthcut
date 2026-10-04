import { Ban, CheckCircle2, Circle, Clock, Hand, Loader2, Lock, MinusCircle, XCircle } from "lucide-react";
import type { StageOut } from "../api/client";
import { STAGE_STATUS_LABEL } from "../strings";
import { ProgressBar, cx } from "./ui";

function StageIcon({ stage }: { stage: StageOut }) {
  const cls = "size-[18px] shrink-0";
  if (!stage.available && stage.status === "pending") return <Lock className={cx(cls, "text-faint")} aria-hidden />;
  switch (stage.status) {
    case "done":
      return <CheckCircle2 className={cx(cls, "text-ok")} aria-hidden />;
    case "running":
      return <Loader2 className={cx(cls, "animate-spin text-run")} aria-hidden />;
    case "queued":
      return <Clock className={cx(cls, "text-warn")} aria-hidden />;
    case "failed":
      return <XCircle className={cx(cls, "text-err")} aria-hidden />;
    case "waiting_user":
      return <Hand className={cx(cls, "text-warn")} aria-hidden />;
    case "skipped":
      return <MinusCircle className={cx(cls, "text-faint")} aria-hidden />;
    case "blocked":
      return <Ban className={cx(cls, "text-err")} aria-hidden />;
    default:
      return <Circle className={cx(cls, "text-faint")} aria-hidden />;
  }
}

export function StageList({ stages }: { stages: StageOut[] }) {
  return (
    <ol className="divide-y divide-line">
      {stages.map((stage) => {
        const active = stage.status === "running" || stage.status === "queued" || stage.status === "waiting_user";
        return (
          <li key={stage.stage} className="flex gap-3 px-4 py-3">
            <div className="pt-px">
              <StageIcon stage={stage} />
            </div>
            <div className="min-w-0 flex-1">
              <div className="flex items-baseline justify-between gap-2">
                <span className={cx("text-sm font-semibold", active ? "text-fg" : stage.status === "done" ? "text-fg" : "text-dim")}>
                  {stage.label}
                </span>
                <span className="shrink-0 text-xs text-faint">
                  {stage.available ? STAGE_STATUS_LABEL[stage.status] : `Phase ${stage.phase}`}
                </span>
              </div>
              {stage.detail && <p className="mt-0.5 truncate text-[13px] text-dim">{stage.detail}</p>}
              {!stage.available && stage.status !== "pending" && (
                <p className="mt-0.5 text-xs text-faint">AI model kaliti ulanganda ishga tushadi</p>
              )}
              {stage.status === "running" && stage.progress != null && (
                <ProgressBar value={stage.progress} tone="run" className="mt-2" />
              )}
            </div>
          </li>
        );
      })}
    </ol>
  );
}
