import { useMutation, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Download, Send, TriangleAlert, XCircle } from "lucide-react";
import { useState } from "react";
import { api, unwrap, type Schemas } from "../api/client";
import type { JobProgress } from "../hooks/useProjectEvents";
import { formatBytes, formatDuration, pct } from "../services/format";
import { stableUrl } from "../services/urlcache";
import { DELIVERY_LABEL, QA_LABEL } from "../strings";
import { downloadFile, haptic } from "../telegram";
import { Feedback } from "./Feedback";
import { Badge, Button, ErrorNote, ProgressBar, cx } from "./ui";

export type RenderOut = Schemas["RenderOut"];

const CHECK_ICON = {
  pass: <CheckCircle2 className="size-3.5 shrink-0 text-ok" aria-hidden />,
  warn: <TriangleAlert className="size-3.5 shrink-0 text-warn" aria-hidden />,
  fail: <XCircle className="size-3.5 shrink-0 text-err" aria-hidden />,
};

export function QaChecks({ qa }: { qa: NonNullable<RenderOut["qa"]> }) {
  return (
    <ul className="space-y-1 text-[12px] text-dim">
      {qa.checks.map((c) => (
        <li key={c.code} className="flex items-start gap-2">
          <span className="mt-0.5">{CHECK_ICON[c.status]}</span>
          {c.message}
        </li>
      ))}
    </ul>
  );
}

/** One final render: progress while it runs, then the video, QA and the ways out of the app. */
export function RenderCard({ projectId, render, live, filename, compact = false }: { projectId: string; render: RenderOut; live?: JobProgress; filename: string; compact?: boolean }) {
  const qc = useQueryClient();
  const [showQa, setShowQa] = useState(!compact);
  const deliver = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/renders/{render_id}/deliver", { params: { path: { render_id: render.id } } })),
    onSuccess: () => {
      haptic.success();
      void qc.invalidateQueries({ queryKey: ["renders", projectId] });
      void qc.invalidateQueries({ queryKey: ["edit", projectId] });
    },
    onError: () => haptic.error(),
  });
  const busy = render.status === "queued" || render.status === "running";
  const v = render.finished_at ?? render.created_at;
  const video = render.video ? stableUrl(`${render.id}:video:${v}`, render.video) : undefined;
  const poster = render.poster ? stableUrl(`${render.id}:poster:${v}`, render.poster) : undefined;
  const qa = render.qa_status ? QA_LABEL[render.qa_status] : null;
  const progress = live?.progress ?? render.progress ?? 0;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-1.5">
        <Badge tone="accent">v{render.plan_version}</Badge>
        {render.duration_sec != null && <Badge>{formatDuration(render.duration_sec)}</Badge>}
        {render.width && render.height && (
          <Badge>
            {render.width}×{render.height}
          </Badge>
        )}
        {render.size_bytes != null && <Badge>{formatBytes(render.size_bytes)}</Badge>}
        {qa && <Badge tone={qa.tone}>{qa.title}</Badge>}
      </div>

      {busy && (
        <div>
          <ProgressBar value={progress} tone="run" />
          <p className="mt-1.5 text-xs text-run">{render.status === "queued" ? "Navbatda" : `${live?.step ?? render.step ?? "boshlanmoqda"} · ${pct(progress)}`}</p>
          <p className="mt-1 text-[11px] text-faint">Asl fayllardan render: daqiqalar oladi, ilovani yopsangiz ham davom etadi.</p>
        </div>
      )}
      {render.status === "failed" && render.error && <ErrorNote>{render.error}</ErrorNote>}

      {video && (
        <video
          src={video}
          poster={poster}
          controls
          playsInline
          preload="metadata"
          className={cx("w-full rounded-xl border border-line bg-black", render.height && render.width && render.height > render.width ? "mx-auto max-h-[70vh] w-auto" : "")}
        />
      )}

      {render.qa && (
        <div>
          {compact && (
            <button type="button" className="text-xs font-semibold text-accent" onClick={() => setShowQa((x) => !x)}>
              {showQa ? "QA'ni yashirish" : "QA tafsilotlari"}
            </button>
          )}
          {showQa && <QaChecks qa={render.qa} />}
        </div>
      )}

      {render.status === "done" && (
        <div className="grid grid-cols-2 gap-2">
          {render.download && (
            <Button size="sm" variant="secondary" icon={<Download className="size-4" />} onClick={() => downloadFile(render.download!.url, `${filename}_v${render.plan_version}.mp4`)}>
              Yuklab olish
            </Button>
          )}
          <Button
            size="sm"
            variant="secondary"
            icon={<Send className="size-4" />}
            loading={deliver.isPending}
            disabled={render.delivery_status === "queued"}
            onClick={() => deliver.mutate()}
          >
            {render.delivery_status === "sent" ? "Yana yuborish" : "Telegramga"}
          </Button>
        </div>
      )}
      {render.status === "done" && render.delivery_status !== "none" && (
        <p className={cx("text-[12px]", render.delivery_status === "failed" ? "text-err" : "text-faint")}>
          {DELIVERY_LABEL[render.delivery_status]}
          {render.delivery_error ? ` — ${render.delivery_error}` : ""}
        </p>
      )}
      {deliver.isError && <ErrorNote>{(deliver.error as Error).message}</ErrorNote>}
      {render.status === "done" && <Feedback projectId={projectId} renderId={render.id} />}
    </div>
  );
}
