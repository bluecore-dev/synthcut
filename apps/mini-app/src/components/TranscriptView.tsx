import { useQuery } from "@tanstack/react-query";
import { memo } from "react";
import { api, unwrap, type Transcript, type TranscriptSummary } from "../api/client";
import { formatDuration } from "../services/format";
import { SPEECH_LANGUAGE_NAME } from "../strings";
import { ErrorNote, Skeleton, cx } from "./ui";

type Segment = Transcript["segments"][number];

export const languageName = (code: string | null | undefined) => (code ? (SPEECH_LANGUAGE_NAME[code] ?? code) : "—");

/** "O'zbek · aniqlandi 81%" / "Русский · tanlangan". */
export function languageNote(t: Pick<TranscriptSummary, "language" | "language_probability" | "requested_language">) {
  const forced = t.requested_language !== "auto";
  const how = forced ? "tanlangan" : t.language_probability != null ? `aniqlandi ${Math.round(t.language_probability * 100)}%` : "aniqlandi";
  return `${languageName(t.language)} · ${how}`;
}

const LOW_CONFIDENCE = 0.5;

const SegmentRow = memo(function SegmentRow({
  seg,
  time,
  onSeek,
}: {
  seg: Segment;
  time: number | null; // only the active segment gets the playhead, so the others never re-render
  onSeek?: (t: number) => void;
}) {
  const active = time !== null;
  return (
    <div className={cx("flex gap-3 px-4 py-2.5", active && "bg-accent/10")}>
      <button
        type="button"
        disabled={!onSeek}
        onClick={() => onSeek?.(seg.start)}
        className="tabular w-10 shrink-0 pt-px text-left text-[11px] text-faint"
      >
        {formatDuration(seg.start)}
      </button>
      <p className={cx("min-w-0 flex-1 text-[14px] leading-relaxed", seg.question ? "text-accent" : "text-fg")}>
        {seg.words.length
          ? seg.words.map((w, i) => {
              const low = w.probability != null && w.probability < LOW_CONFIDENCE;
              const now = time !== null && time >= w.start && time < w.end;
              return (
                <span key={i}>
                  {i > 0 && " "}
                  <span
                    role={onSeek ? "button" : undefined}
                    onClick={onSeek ? () => onSeek(w.start) : undefined}
                    title={low ? `ishonch ${Math.round((w.probability ?? 0) * 100)}%` : undefined}
                    className={cx(
                      "rounded-sm",
                      low && "text-dim underline decoration-warn/60 decoration-dotted underline-offset-4",
                      now && "bg-accent/30 text-fg",
                    )}
                  >
                    {w.word}
                  </span>
                </span>
              );
            })
          : seg.text}
      </p>
    </div>
  );
});

/** Segments of a finished transcript; words are tappable when ``onSeek`` is given.
 * ``version`` (the transcript's finish time) keys the cache, so a re-run is fetched anew. */
export function TranscriptView({
  assetId,
  version,
  currentTime = null,
  onSeek,
  maxSegments,
}: {
  assetId: string;
  version: string | null | undefined;
  currentTime?: number | null;
  onSeek?: (t: number) => void;
  maxSegments?: number;
}) {
  const q = useQuery({
    queryKey: ["transcript", assetId, version],
    queryFn: () => unwrap(api.GET("/api/v1/assets/{asset_id}/transcript", { params: { path: { asset_id: assetId } } })),
    staleTime: Infinity,
  });
  if (q.isPending) return <Skeleton className="m-3 h-24" />;
  if (q.isError) return <ErrorNote>{(q.error as Error).message}</ErrorNote>;
  const t = q.data;
  if (!t.segments.length) {
    return <p className="px-4 py-6 text-center text-sm text-faint">Bu faylda nutq topilmadi.</p>;
  }
  const shown = maxSegments ? t.segments.slice(0, maxSegments) : t.segments;
  return (
    <div className="divide-y divide-line">
      {shown.map((seg) => (
        <SegmentRow
          key={seg.id}
          seg={seg}
          time={currentTime !== null && currentTime >= seg.start && currentTime < seg.end + 0.3 ? currentTime : null}
          onSeek={onSeek}
        />
      ))}
      {shown.length < t.segments.length && (
        <p className="px-4 py-2.5 text-center text-xs text-faint">… yana {t.segments.length - shown.length} ta bo'lak</p>
      )}
    </div>
  );
}
