import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Clapperboard, Download, RefreshCw } from "lucide-react";
import { useState } from "react";
import { api, unwrap, type Schemas } from "../api/client";
import type { JobProgress } from "../hooks/useProjectEvents";
import { pct } from "../services/format";
import { stableUrl } from "../services/urlcache";
import { CAPTION_POSITION_LABEL, CAPTION_STYLE_LABEL } from "../strings";
import { downloadFile, haptic } from "../telegram";
import { Button, Chip, ErrorNote, ProgressBar } from "./ui";

type Preview = Schemas["CaptionPreviewOut"];
type Style = keyof typeof CAPTION_STYLE_LABEL;
type Position = keyof typeof CAPTION_POSITION_LABEL;
const STYLES = Object.keys(CAPTION_STYLE_LABEL) as Style[];
const POSITIONS = Object.keys(CAPTION_POSITION_LABEL) as Position[];

/** Phase 7 made visible: the clip with animated captions burned in (Remotion layer + FFmpeg). */
export function CaptionPreview({
  assetId,
  filename,
  state,
  live,
}: {
  assetId: string;
  filename: string;
  state: Preview | null | undefined;
  live: JobProgress | undefined;
}) {
  const qc = useQueryClient();
  const [style, setStyle] = useState<Style>((state?.style as Style | undefined) ?? "dynamic");
  const [position, setPosition] = useState<Position>((state?.position as Position | undefined) ?? "bottom");
  const run = useMutation({
    mutationFn: () =>
      unwrap(api.POST("/api/v1/assets/{asset_id}/caption-preview", { params: { path: { asset_id: assetId } }, body: { style, position } })),
    onSuccess: () => {
      haptic.success();
      void qc.invalidateQueries({ queryKey: ["asset", assetId] });
    },
    onError: () => haptic.error(),
  });
  const busy = state?.status === "queued" || state?.status === "running";
  const video = state?.video ? stableUrl(`${assetId}:captions:${state.updated_at}`, state.video) : undefined;

  return (
    <div className="space-y-3 px-4 py-3">
      <div className="flex items-center gap-2">
        <Clapperboard className="size-4 text-accent" aria-hidden />
        <p className="text-sm font-semibold">Subtitrli video</p>
        {state?.status === "done" && <span className="ml-auto text-xs text-faint">{CAPTION_STYLE_LABEL[state.style as Style]?.title}</span>}
      </div>

      {video && !busy && (
        <div className="overflow-hidden rounded-xl border border-line bg-black">
          <video src={video} controls playsInline preload="metadata" className="mx-auto max-h-[60vh] w-full" />
        </div>
      )}
      {video && !busy && state?.download && (
        <Button size="sm" variant="secondary" className="w-full" icon={<Download className="size-4" />} onClick={() => downloadFile(state.download!.url, `${filename.replace(/\.[^.]+$/, "")}_subtitr.mp4`)}>
          MP4 yuklab olish
        </Button>
      )}

      {busy && (
        <div>
          <ProgressBar value={live?.progress ?? 0} tone="run" />
          <p className="mt-1.5 text-xs text-run">
            {state?.status === "queued" ? "Navbatda" : `${live?.step === "kompozit" ? "Videoga qo'shilmoqda" : "Animatsiya chizilmoqda"} · ${live ? pct(live.progress) : "boshlanmoqda"}`}
          </p>
        </div>
      )}
      {state?.status === "failed" && state.error && <ErrorNote>{state.error}</ErrorNote>}

      {!busy && (
        <>
          <div className="grid grid-cols-2 gap-2">
            {STYLES.map((s) => (
              <button
                type="button"
                key={s}
                onClick={() => {
                  haptic.select();
                  setStyle(s);
                }}
                className={`rounded-xl border px-3 py-2 text-left ${style === s ? "border-accent/60 bg-accent/15" : "border-line bg-s1 active:bg-s2"}`}
              >
                <p className="text-[13px] font-semibold">{CAPTION_STYLE_LABEL[s].title}</p>
                <p className="mt-0.5 text-[11px] leading-snug text-faint">{CAPTION_STYLE_LABEL[s].hint}</p>
              </button>
            ))}
          </div>
          <div className="flex gap-2">
            {POSITIONS.map((p) => (
              <Chip key={p} active={position === p} onClick={() => setPosition(p)}>
                {CAPTION_POSITION_LABEL[p]}
              </Chip>
            ))}
          </div>
          <Button className="w-full" variant="primary" loading={run.isPending} icon={video ? <RefreshCw className="size-4" /> : <Clapperboard className="size-4" />} onClick={() => run.mutate()}>
            {video ? "Qayta yaratish" : "Video yaratish"}
          </Button>
          {run.isError && <ErrorNote>{(run.error as Error).message}</ErrorNote>}
        </>
      )}
    </div>
  );
}
