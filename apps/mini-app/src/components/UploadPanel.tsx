import { CloudUpload, Pause, Play, RotateCcw, X } from "lucide-react";
import { useRef } from "react";
import { useUploads } from "../hooks/useUploads";
import { formatBytes, formatEta, formatSpeed, pct } from "../services/format";
import { uploads, type UploadPhase, type UploadView } from "../services/uploader";
import { UPLOAD_HINT_IOS } from "../strings";
import { tg } from "../telegram";
import { Badge, Button, Card, ProgressBar } from "./ui";

const ACCEPT = "video/*,audio/*,image/*,.mov,.mp4,.m4v,.mxf,.mkv,.braw,.r3d,.crm,.wav,.aif,.aiff,.flac,.dng";

const PHASE_LABEL: Record<UploadPhase, string> = {
  queued: "Navbatda",
  preparing: "Tayyorlanmoqda",
  verifying: "Avvalgi qismlar tekshirilmoqda",
  uploading: "Yuklanmoqda",
  paused: "Pauza",
  offline: "Internet kutilmoqda",
  completing: "Yakunlanmoqda",
  done: "Yuklandi",
  duplicate: "Allaqachon yuklangan",
  error: "Xato",
  cancelled: "Bekor qilindi",
};

const VISIBLE: UploadPhase[] = ["queued", "preparing", "verifying", "uploading", "paused", "offline", "completing", "error", "duplicate"];

function UploadRow({ u }: { u: UploadView }) {
  const fraction = u.size ? u.uploaded / u.size : 0;
  const remaining = u.speed > 0 ? (u.size - u.uploaded) / u.speed : Number.NaN;
  const tone = u.phase === "error" ? "err" : u.phase === "paused" || u.phase === "offline" ? "warn" : "accent";
  return (
    <li className="px-4 py-3">
      <div className="flex items-center gap-2">
        <p className="min-w-0 flex-1 truncate text-sm font-medium text-fg">{u.name}</p>
        {u.resumed && u.phase === "uploading" && <Badge tone="run">davom</Badge>}
        <span className="tabular shrink-0 text-xs text-faint">{formatBytes(u.size)}</span>
      </div>
      {u.phase !== "duplicate" && <ProgressBar value={fraction} tone={tone} className="mt-2" />}
      <div className="mt-1.5 flex items-center gap-2 text-xs">
        <span className={u.phase === "error" ? "text-err" : u.phase === "paused" || u.phase === "offline" ? "text-warn" : "text-dim"}>
          {PHASE_LABEL[u.phase]}
          {u.phase === "uploading" && ` · ${pct(fraction)}`}
        </span>
        {u.phase === "uploading" && (
          <span className="tabular text-faint">
            {formatSpeed(u.speed)} · {formatEta(remaining)}
          </span>
        )}
        <span className="ml-auto flex items-center gap-1">
          {(u.phase === "uploading" || u.phase === "queued" || u.phase === "offline") && (
            <Button size="sm" variant="ghost" aria-label="Pauza" icon={<Pause className="size-4" />} onClick={() => uploads.pause(u.id)} />
          )}
          {u.phase === "paused" && (
            <Button size="sm" variant="ghost" aria-label="Davom ettirish" icon={<Play className="size-4" />} onClick={() => uploads.resume(u.id)} />
          )}
          {u.phase === "error" && (
            <Button size="sm" variant="ghost" aria-label="Qayta urinish" icon={<RotateCcw className="size-4" />} onClick={() => uploads.resume(u.id)} />
          )}
          {u.phase === "duplicate" ? (
            <Button size="sm" variant="ghost" aria-label="Yopish" icon={<X className="size-4" />} onClick={() => uploads.dismiss(u.id)} />
          ) : (
            u.phase !== "completing" && (
              <Button size="sm" variant="ghost" aria-label="Bekor qilish" icon={<X className="size-4" />} onClick={() => void uploads.cancel(u.id)} />
            )
          )}
        </span>
      </div>
      {u.error && <p className="mt-1 text-xs text-err">{u.error}</p>}
      {u.partCount > 0 && u.phase === "uploading" && (
        <p className="tabular mt-0.5 text-[11px] text-faint">
          {u.partsDone}/{u.partCount} qism tasdiqlandi (MD5)
        </p>
      )}
    </li>
  );
}

export function UploadPanel({ projectId, disabled }: { projectId: string; disabled?: boolean }) {
  const input = useRef<HTMLInputElement>(null);
  const items = useUploads(projectId).filter((u) => VISIBLE.includes(u.phase));
  const total = items.reduce((s, u) => s + u.size, 0);
  const done = items.reduce((s, u) => s + u.uploaded, 0);
  const active = items.filter((u) => u.phase === "uploading").length;

  return (
    <Card>
      <div className="flex items-center gap-3 p-4">
        <div className="grid size-10 shrink-0 place-items-center rounded-xl bg-brand/15 text-accent">
          <CloudUpload className="size-5" aria-hidden />
        </div>
        <div className="min-w-0 flex-1">
          <p className="text-sm font-semibold">Xom materiallarni yuklash</p>
          <p className="text-xs text-dim">To'g'ridan-to'g'ri saqlash tizimiga · uzilsa davom etadi</p>
        </div>
        <Button variant="primary" size="sm" disabled={disabled} onClick={() => input.current?.click()}>
          Fayl qo'shish
        </Button>
        <input
          ref={input}
          type="file"
          multiple
          accept={ACCEPT}
          className="hidden"
          onChange={(e) => {
            const files = Array.from(e.target.files ?? []);
            if (files.length) uploads.add(projectId, files);
            e.target.value = "";
          }}
        />
      </div>
      {tg?.platform === "ios" && <p className="border-t border-line px-4 py-2.5 text-xs text-faint">{UPLOAD_HINT_IOS}</p>}
      {items.length > 0 && (
        <>
          {items.length > 1 && (
            <div className="border-t border-line px-4 py-2.5">
              <div className="flex justify-between text-xs text-dim">
                <span>
                  Jami {items.length} ta fayl{active ? ` · ${active} ta faol` : ""}
                </span>
                <span className="tabular">
                  {formatBytes(done)} / {formatBytes(total)}
                </span>
              </div>
              <ProgressBar value={total ? done / total : 0} className="mt-1.5" />
            </div>
          )}
          <ul className="divide-y divide-line border-t border-line">
            {items.map((u) => (
              <UploadRow key={u.id} u={u} />
            ))}
          </ul>
        </>
      )}
    </Card>
  );
}
