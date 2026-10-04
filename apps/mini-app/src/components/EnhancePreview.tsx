import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Download, RefreshCw, Sparkles } from "lucide-react";
import { useState } from "react";
import { api, unwrap, type Schemas } from "../api/client";
import type { JobProgress } from "../hooks/useProjectEvents";
import { pct } from "../services/format";
import { stableUrl } from "../services/urlcache";
import { ENHANCE_PROFILE_LABEL, LOUDNESS_TARGET_LABEL } from "../strings";
import { downloadFile, haptic } from "../telegram";
import { BeforeAfter } from "./BeforeAfter";
import { Button, Card, Chip, ErrorNote, ProgressBar, SectionLabel } from "./ui";

type State = Schemas["EnhancePreviewOut"];
type Profile = keyof typeof ENHANCE_PROFILE_LABEL;
type Target = keyof typeof LOUDNESS_TARGET_LABEL;
const PROFILES = Object.keys(ENHANCE_PROFILE_LABEL) as Profile[];
const TARGETS = Object.keys(LOUDNESS_TARGET_LABEL) as Target[];
const INTENSITY = [0.5, 0.8, 1];
const DENOISE = { auto: "Avto", off: "O'chiq", light: "Yengil", medium: "O'rta", strong: "Kuchli" } as const;
type Denoise = keyof typeof DENOISE;

/** Phase 8 made visible: automatic grade + voice cleanup and loudness on one clip. */
export function EnhancePreview({ assetId, filename, state, live }: { assetId: string; filename: string; state: State | null | undefined; live: JobProgress | undefined }) {
  const qc = useQueryClient();
  const [profile, setProfile] = useState<Profile>((state?.profile as Profile | undefined) ?? "cinematic_clean");
  const [intensity, setIntensity] = useState<number>(state?.intensity ?? 0.8);
  const [target, setTarget] = useState<Target>((state?.target as Target | undefined) ?? "social");
  const [denoise, setDenoise] = useState<Denoise>("auto");
  const run = useMutation({
    mutationFn: () =>
      unwrap(api.POST("/api/v1/assets/{asset_id}/enhance-preview", { params: { path: { asset_id: assetId } }, body: { profile, intensity, target, denoise } })),
    onSuccess: () => {
      haptic.success();
      void qc.invalidateQueries({ queryKey: ["asset", assetId] });
    },
    onError: () => haptic.error(),
  });
  const busy = state?.status === "queued" || state?.status === "running";
  const v = state?.updated_at ?? "";
  const video = state?.video ? stableUrl(`${assetId}:enhanced:${v}`, state.video) : undefined;
  const before = state?.before ? stableUrl(`${assetId}:before:${v}`, state.before) : undefined;
  const after = state?.after ? stableUrl(`${assetId}:after:${v}`, state.after) : undefined;

  return (
    <div>
      <SectionLabel right={state?.status === "done" ? <span className="text-xs text-faint">{ENHANCE_PROFILE_LABEL[state.profile as Profile]?.title}</span> : null}>Rang va ovoz</SectionLabel>
      <Card className="space-y-3 p-4">
        {before && after && !busy && <BeforeAfter before={before} after={after} />}
        {state?.status === "done" && (state.notes?.length ?? 0) > 0 && !busy && (
          <ul className="space-y-1 text-[12px] text-dim">
            {(state.notes ?? []).map((n, i) => (
              <li key={i} className="flex gap-2">
                <Sparkles className="mt-0.5 size-3 shrink-0 text-accent" aria-hidden />
                {n}
              </li>
            ))}
          </ul>
        )}
        {video && !busy && <video src={video} controls playsInline preload="metadata" className="w-full rounded-xl border border-line bg-black" />}
        {video && !busy && state?.download && (
          <Button size="sm" variant="secondary" className="w-full" icon={<Download className="size-4" />} onClick={() => downloadFile(state.download!.url, `${filename.replace(/\.[^.]+$/, "")}_enhanced.mp4`)}>
            MP4 yuklab olish
          </Button>
        )}
        {busy && (
          <div>
            <ProgressBar value={live?.progress ?? 0} tone="run" />
            <p className="mt-1.5 text-xs text-run">{state?.status === "queued" ? "Navbatda" : `${live?.step ?? "boshlanmoqda"} · ${live ? pct(live.progress) : ""}`}</p>
          </div>
        )}
        {state?.status === "failed" && state.error && <ErrorNote>{state.error}</ErrorNote>}
        {!busy && (
          <>
            <div className="grid grid-cols-2 gap-2">
              {PROFILES.map((p) => (
                <button
                  type="button"
                  key={p}
                  onClick={() => {
                    haptic.select();
                    setProfile(p);
                  }}
                  className={`rounded-xl border px-3 py-2 text-left ${profile === p ? "border-accent/60 bg-accent/15" : "border-line bg-s1 active:bg-s2"}`}
                >
                  <p className="text-[13px] font-semibold">{ENHANCE_PROFILE_LABEL[p].title}</p>
                  <p className="mt-0.5 text-[11px] leading-snug text-faint">{ENHANCE_PROFILE_LABEL[p].hint}</p>
                </button>
              ))}
            </div>
            <div className="flex flex-wrap gap-2">
              {INTENSITY.map((x) => (
                <Chip key={x} active={intensity === x} onClick={() => setIntensity(x)}>
                  {Math.round(x * 100)}%
                </Chip>
              ))}
            </div>
            <div className="flex flex-wrap gap-2">
              {TARGETS.map((t) => (
                <Chip key={t} active={target === t} onClick={() => setTarget(t)}>
                  {LOUDNESS_TARGET_LABEL[t]}
                </Chip>
              ))}
            </div>
            <div>
              <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-faint">Shovqin tozalash</p>
              <div className="flex flex-wrap gap-2">
                {(Object.keys(DENOISE) as Denoise[]).map((d) => (
                  <Chip key={d} active={denoise === d} onClick={() => setDenoise(d)}>
                    {DENOISE[d]}
                  </Chip>
                ))}
              </div>
              <p className="mt-1 text-[11px] text-faint">Fon musiqasi bo'lsa "Yengil" yoki "O'chiq" tanlang — kuchli tozalash musiqani ham bosadi.</p>
            </div>
            <Button className="w-full" variant="primary" loading={run.isPending} icon={video ? <RefreshCw className="size-4" /> : <Sparkles className="size-4" />} onClick={() => run.mutate()}>
              {video ? "Qayta yaxshilash" : "Rang va ovozni yaxshilash"}
            </Button>
            {run.isError && <ErrorNote>{(run.error as Error).message}</ErrorNote>}
          </>
        )}
      </Card>
    </div>
  );
}
