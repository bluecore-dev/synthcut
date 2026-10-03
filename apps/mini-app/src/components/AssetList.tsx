import { useQueryClient } from "@tanstack/react-query";
import { ChevronRight, FileAudio, FileImage, FileVideo, Files, X } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";
import { api, unwrap, type AssetOut } from "../api/client";
import type { RemoteUploadProgress } from "../hooks/useProjectEvents";
import { useUploads } from "../hooks/useUploads";
import { formatBytes, formatDuration, pct } from "../services/format";
import { stableUrl } from "../services/urlcache";
import { ASSET_STATUS_LABEL } from "../strings";
import { confirmDialog } from "../telegram";
import { Badge, Button, EmptyState, ProgressBar, cx } from "./ui";

const KIND_ICON = { video: FileVideo, audio: FileAudio, image: FileImage, other: Files } as const;
const STATUS_TONE = {
  uploading: "run",
  uploaded: "warn",
  ingesting: "run",
  ready: "ok",
  failed: "err",
  cancelled: "neutral",
} as const;

const LOCAL_ACTIVE = new Set(["queued", "preparing", "verifying", "uploading", "paused", "offline", "completing", "error"]);

export function colorTone(profile: string | null | undefined) {
  if (!profile) return "neutral" as const;
  if (profile === "hlg" || profile === "pq") return "warn" as const;
  if (profile.includes("log")) return "accent" as const;
  return "neutral" as const;
}

export function AssetList({
  projectId,
  assets,
  remote,
  ingest,
}: {
  projectId: string;
  assets: AssetOut[];
  remote: Record<string, RemoteUploadProgress>;
  ingest: Record<string, { progress: number; step: string }>;
}) {
  const local = useUploads(projectId);
  const qc = useQueryClient();
  const [cancelling, setCancelling] = useState<string | null>(null);
  const cancelStalled = async (asset: AssetOut) => {
    if (!asset.upload || !(await confirmDialog(`${asset.original_filename} yuklashini bekor qilasizmi?`))) return;
    setCancelling(asset.id);
    try {
      await unwrap(api.DELETE("/api/v1/uploads/{session_id}", { params: { path: { session_id: asset.upload.session_id } } }));
    } finally {
      setCancelling(null);
      void qc.invalidateQueries({ queryKey: ["assets", projectId] });
      void qc.invalidateQueries({ queryKey: ["project", projectId] });
    }
  };
  const handledLocally = new Set(local.filter((u) => u.assetId && LOCAL_ACTIVE.has(u.phase)).map((u) => u.assetId));
  const visible = assets.filter((a) => !handledLocally.has(a.id) && a.status !== "cancelled");

  if (!visible.length) {
    return (
      <EmptyState icon={<FileVideo className="size-6" />} title="Hali material yo'q">
        RAW / Log videolar, ovoz va rasmlarni yuklang. Original fayl hech qachon o'zgartirilmaydi.
      </EmptyState>
    );
  }

  return (
    <ul className="divide-y divide-line">
      {visible.map((a) => {
        const Icon = KIND_ICON[a.kind];
        const live = remote[a.id];
        const reported = live && Date.now() - live.at < 30_000 ? live.bytes : (a.upload?.bytes_reported ?? 0);
        const stalled = a.status === "uploading" && !(live && Date.now() - live.at < 30_000);
        const thumb = stableUrl(`${a.id}:poster`, a.thumbnail);
        const work = ingest[a.id];
        const meta = [
          a.duration_sec ? formatDuration(a.duration_sec) : null,
          a.width && a.height ? `${a.width}×${a.height}` : null,
          a.fps ? `${Math.round(a.fps * 100) / 100} fps` : null,
          a.video_codec ? a.video_codec.toUpperCase() : null,
          a.status === "ready" && a.kind === "video" && a.has_audio === false ? "ovozsiz" : null,
          formatBytes(a.size_bytes),
        ].filter(Boolean);
        const openable = a.status === "ready" || a.status === "failed";
        const body = (
          <div className="flex gap-3 px-4 py-3">
            <div className="relative grid size-14 shrink-0 place-items-center overflow-hidden rounded-xl border border-line bg-s2 text-dim">
              {thumb ? (
                <img src={thumb} alt="" loading="lazy" className="size-full object-cover" />
              ) : (
                <Icon className="size-5" aria-hidden />
              )}
            </div>
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <p className="min-w-0 flex-1 truncate text-sm font-medium">{a.original_filename}</p>
                <Badge tone={STATUS_TONE[a.status]}>{a.status === "uploaded" ? "navbatda" : ASSET_STATUS_LABEL[a.status]}</Badge>
              </div>
              <p className="tabular mt-0.5 truncate text-xs text-faint">{meta.join(" · ")}</p>
              {a.color_label && a.kind !== "audio" && (
                <div className="mt-1.5 flex gap-1.5">
                  <Badge tone={colorTone(a.color_profile)}>{a.color_label}</Badge>
                  {a.bit_depth && a.bit_depth > 8 && <Badge>{a.bit_depth}-bit</Badge>}
                </div>
              )}
              {a.status === "ingesting" && (
                <>
                  <ProgressBar value={work?.progress ?? 0} tone="run" className="mt-2" />
                  <p className="mt-1 text-xs text-run">Tahlil · {work ? `${work.step} · ${pct(work.progress)}` : "boshlanmoqda"}</p>
                </>
              )}
              {a.status === "uploading" && (
                <>
                  <ProgressBar value={a.size_bytes ? reported / a.size_bytes : 0} tone={stalled ? "warn" : "run"} className="mt-2" />
                  <div className="mt-1 flex items-start gap-2">
                    <p className="flex-1 text-xs text-warn">
                      {stalled
                        ? `To'xtatilgan (${pct(reported / a.size_bytes)}) — davom ettirish uchun xuddi shu faylni qayta tanlang`
                        : `Boshqa qurilmadan yuklanmoqda · ${pct(reported / a.size_bytes)}`}
                    </p>
                    {stalled && a.upload && (
                      <Button
                        size="sm"
                        variant="ghost"
                        aria-label="Bekor qilish"
                        loading={cancelling === a.id}
                        icon={<X className="size-4" />}
                        onClick={(e) => {
                          e.preventDefault();
                          void cancelStalled(a);
                        }}
                      />
                    )}
                  </div>
                </>
              )}
              {a.error && a.status === "failed" && <p className="mt-1 text-xs text-err">{a.error}</p>}
            </div>
            {openable && <ChevronRight className="mt-4 size-4 shrink-0 text-faint" aria-hidden />}
          </div>
        );
        return (
          <li key={a.id} className={cx(openable && "active:bg-s2")}>
            {openable ? <Link to={`/p/${projectId}/a/${a.id}`}>{body}</Link> : body}
          </li>
        );
      })}
    </ul>
  );
}
