import { AudioLines, Copy, Users } from "lucide-react";
import type { ClipOut } from "../api/client";
import { formatDuration, pct } from "../services/format";
import { stableUrl } from "../services/urlcache";
import { CAMERA_MOTION_LABEL, CLIP_FLAG_LABEL, SHOT_TYPE_LABEL, SUBJECT_LABEL } from "../strings";
import { Badge, cx } from "./ui";

const scoreTone = (v: number) => (v >= 0.75 ? "bg-ok" : v >= 0.5 ? "bg-warn" : "bg-err");

function Meter({ label, value }: { label: string; value: number }) {
  return (
    <div className="min-w-0 flex-1">
      <div className="flex justify-between text-[10px] text-faint">
        <span className="truncate">{label}</span>
        <span className="tabular">{pct(value)}</span>
      </div>
      <div className="mt-0.5 h-1 overflow-hidden rounded-full bg-s2">
        <div className={cx("h-full rounded-full", scoreTone(value))} style={{ width: pct(value) }} />
      </div>
    </div>
  );
}

/** One analysed shot: three stills, what it is, how good it is, what is wrong with it. */
export function ClipCard({ clip, onOpen, showAsset = false }: { clip: ClipOut; onOpen?: () => void; showAsset?: boolean }) {
  const sheet = stableUrl(`${clip.clip_id}:sheet`, clip.sheet);
  return (
    <button type="button" onClick={onOpen} disabled={!onOpen} className="block w-full px-4 py-3 text-left active:bg-s2">
      {sheet && <img src={sheet} alt="" loading="lazy" className="w-full rounded-lg border border-line bg-black" />}
      <div className="mt-2 flex items-center gap-2">
        <span className="tabular text-xs font-semibold text-fg">
          #{clip.index + 1} · {formatDuration(clip.start)}–{formatDuration(clip.end)}
        </span>
        <span className="tabular text-[11px] text-faint">{clip.duration.toFixed(1)}s</span>
        <span className={cx("ml-auto tabular text-xs font-bold", clip.usable_score >= 0.75 ? "text-ok" : clip.usable_score >= 0.5 ? "text-warn" : "text-err")}>
          {pct(clip.usable_score)}
        </span>
      </div>
      {showAsset && <p className="mt-0.5 truncate text-[11px] text-faint">{clip.asset_name}</p>}
      <div className="mt-1.5 flex flex-wrap gap-1.5">
        <Badge>{SHOT_TYPE_LABEL[clip.shot_type]}</Badge>
        <Badge>{CAMERA_MOTION_LABEL[clip.camera_motion]}</Badge>
        {clip.subject && (
          <Badge>
            <Users className="size-3" aria-hidden />
            {SUBJECT_LABEL[clip.subject] ?? clip.subject}
            {clip.person_position && clip.face_count === 1 ? ` · ${clip.person_position === "left" ? "chapda" : clip.person_position === "right" ? "o'ngda" : "markazda"}` : ""}
          </Badge>
        )}
        {clip.speech_present && (
          <Badge tone="accent">
            <AudioLines className="size-3" aria-hidden />
            nutq {pct(clip.speech_ratio)}
          </Badge>
        )}
        {clip.flags.map((f) => (
          <Badge key={f} tone={f === "duplicate" ? "neutral" : "warn"}>
            {f === "duplicate" && <Copy className="size-3" aria-hidden />}
            {CLIP_FLAG_LABEL[f]}
          </Badge>
        ))}
      </div>
      <div className="mt-2 flex gap-3">
        <Meter label="Kamera" value={clip.camera_quality} />
        <Meter label="Yorug'lik" value={clip.lighting_quality} />
        <Meter label="Aniqlik" value={clip.sharpness} />
      </div>
      {clip.semantic_description && <p className="mt-2 text-[13px] text-dim">{clip.semantic_description}</p>}
    </button>
  );
}
