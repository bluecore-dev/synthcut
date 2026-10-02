import { FileAudio, FileImage, FileVideo, Files } from "lucide-react";
import type { AssetOut } from "../api/client";
import type { RemoteUploadProgress } from "../hooks/useProjectEvents";
import { useUploads } from "../hooks/useUploads";
import { formatBytes, formatDuration, pct } from "../services/format";
import { ASSET_STATUS_LABEL } from "../strings";
import { Badge, EmptyState, ProgressBar } from "./ui";

const KIND_ICON = { video: FileVideo, audio: FileAudio, image: FileImage, other: Files } as const;
const STATUS_TONE = {
  uploading: "run",
  uploaded: "accent",
  ingesting: "run",
  ready: "ok",
  failed: "err",
  cancelled: "neutral",
} as const;

const LOCAL_ACTIVE = new Set(["queued", "preparing", "verifying", "uploading", "paused", "offline", "completing", "error"]);

export function AssetList({
  projectId,
  assets,
  remote,
}: {
  projectId: string;
  assets: AssetOut[];
  remote: Record<string, RemoteUploadProgress>;
}) {
  const local = useUploads(projectId);
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
        const meta = [
          formatBytes(a.size_bytes),
          a.width && a.height ? `${a.width}×${a.height}` : null,
          a.fps ? `${Math.round(a.fps * 100) / 100} fps` : null,
          a.duration_sec ? formatDuration(a.duration_sec) : null,
        ].filter(Boolean);
        return (
          <li key={a.id} className="flex gap-3 px-4 py-3">
            <div className="grid size-10 shrink-0 place-items-center rounded-xl border border-line bg-s2 text-dim">
              <Icon className="size-5" aria-hidden />
            </div>
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <p className="min-w-0 flex-1 truncate text-sm font-medium">{a.original_filename}</p>
                <Badge tone={STATUS_TONE[a.status]}>{ASSET_STATUS_LABEL[a.status]}</Badge>
              </div>
              <p className="tabular mt-0.5 text-xs text-faint">{meta.join(" · ")}</p>
              {a.status === "uploading" && (
                <>
                  <ProgressBar value={a.size_bytes ? reported / a.size_bytes : 0} tone={stalled ? "warn" : "run"} className="mt-2" />
                  <p className="mt-1 text-xs text-warn">
                    {stalled
                      ? `To'xtatilgan (${pct(reported / a.size_bytes)}) — davom ettirish uchun xuddi shu faylni qayta tanlang`
                      : `Boshqa qurilmadan yuklanmoqda · ${pct(reported / a.size_bytes)}`}
                  </p>
                </>
              )}
              {a.error && a.status === "failed" && <p className="mt-1 text-xs text-err">{a.error}</p>}
            </div>
          </li>
        );
      })}
    </ul>
  );
}
