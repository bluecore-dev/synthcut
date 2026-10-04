import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, Scissors, Sparkles, Wand2 } from "lucide-react";
import { useState } from "react";
import { api, unwrap, type ProjectOut, type Schemas } from "../api/client";
import type { JobProgress } from "../hooks/useProjectEvents";
import { pct } from "../services/format";
import { AUTO_EDIT_DURATIONS, CAPTION_STYLE_LABEL, ENHANCE_PROFILE_LABEL, LOUDNESS_TARGET_LABEL, PLAN_SOURCE_LABEL } from "../strings";
import { haptic } from "../telegram";
import { RenderCard } from "./RenderCard";
import { Button, Card, Chip, ErrorNote, ProgressBar, SectionLabel, Skeleton, cx } from "./ui";

type Request = Schemas["AutoEditRequest"];
type Captions = NonNullable<Request["captions"]>;
type Profile = keyof typeof ENHANCE_PROFILE_LABEL;
type Loudness = keyof typeof LOUDNESS_TARGET_LABEL;
const CAPTIONS: Captions[] = ["dynamic", "karaoke", "minimal", "bold", "off"];
const DENOISE = { auto: "Avto", off: "O'chiq", light: "Yengil", medium: "O'rta", strong: "Kuchli" } as const;
type Denoise = keyof typeof DENOISE;

function durationLabel(sec: number | null): string {
  if (sec == null) return "Hammasi";
  return sec < 60 ? `${sec} s` : `${sec / 60} daq`;
}

function Toggle({ on, onChange, children }: { on: boolean; onChange: (v: boolean) => void; children: string }) {
  return (
    <button
      type="button"
      onClick={() => {
        haptic.select();
        onChange(!on);
      }}
      className="flex w-full items-center justify-between gap-3 py-1.5 text-left text-[13px]"
    >
      <span>{children}</span>
      <span className={cx("relative h-6 w-10 shrink-0 rounded-full transition-colors", on ? "bg-accent" : "bg-line")}>
        <span className={cx("absolute top-0.5 size-5 rounded-full bg-white transition-all", on ? "left-[18px]" : "left-0.5")} />
      </span>
    </button>
  );
}

/** "Tez montaj": the whole pipeline without the AI Director — rules on measured material. */
export function AutoEdit({ project, edit, render }: { project: ProjectOut; edit: JobProgress | null; render: Record<string, JobProgress> }) {
  const qc = useQueryClient();
  const state = useQuery({
    queryKey: ["edit", project.id],
    queryFn: () => unwrap(api.GET("/api/v1/projects/{project_id}/edit", { params: { path: { project_id: project.id } } })),
  });
  const [open, setOpen] = useState(false);
  const [duration, setDuration] = useState<number | null>(project.target_duration_sec ?? null);
  const [captions, setCaptions] = useState<Captions>("dynamic");
  const [profile, setProfile] = useState<Profile>("cinematic_clean");
  const [loudness, setLoudness] = useState<Loudness>("social");
  const [denoise, setDenoise] = useState<Denoise>("auto");
  const [cutPauses, setCutPauses] = useState(true);
  const [deliver, setDeliver] = useState(true);
  const [title, setTitle] = useState("");
  const [cta, setCta] = useState("");

  const run = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST("/api/v1/projects/{project_id}/auto-edit", {
          params: { path: { project_id: project.id } },
          body: {
            target_duration: duration,
            captions,
            caption_position: "bottom",
            profile,
            intensity: 0.8,
            loudness,
            denoise,
            remove_pauses: cutPauses,
            render: true,
            deliver,
            title: title.trim() || null,
            cta: cta.trim() || null,
          },
        }),
      ),
    onSuccess: (data) => {
      haptic.success();
      qc.setQueryData(["edit", project.id], data);
      setOpen(false);
    },
    onError: () => haptic.error(),
  });

  const job = state.data?.job;
  const planning = job != null && (job.status === "queued" || job.status === "running");
  const latest = state.data?.render;
  const rendering = latest != null && (latest.status === "queued" || latest.status === "running");
  const busy = planning || rendering;
  const jobFailed = job != null && (job.status === "dead" || job.status === "cancelled");
  const archived = project.status === "archived";

  return (
    <div>
      <SectionLabel right={state.data?.plan ? <span className="text-xs text-faint">{PLAN_SOURCE_LABEL[state.data.plan.source]} v{state.data.plan.version}</span> : null}>Tez montaj</SectionLabel>
      <Card className="space-y-3 p-4">
        {state.isPending && <Skeleton className="h-24" />}
        {!state.isPending && !state.data?.plan && !planning && (
          <p className="text-[13px] leading-relaxed text-dim">
            Pauzalar va yaroqsiz kadrlar kesiladi, kadr formatga moslanadi (yuz markazda), rang va ovoz tuzatiladi, subtitr qo'yiladi — keyin asl fayllardan render va Telegramga yuborish.
          </p>
        )}

        {planning && (
          <div>
            <ProgressBar value={edit?.progress ?? 0} tone="run" />
            <p className="mt-1.5 text-xs text-run">{job?.status === "queued" ? "Navbatda" : `${edit?.step ?? job?.step ?? "boshlanmoqda"} · ${pct(edit?.progress ?? job?.progress ?? 0)}`}</p>
          </div>
        )}
        {jobFailed && job?.error && !latest && <ErrorNote>{job.error}</ErrorNote>}

        {state.data?.plan?.notes && !planning && (
          <ul className="space-y-1 text-[12px] text-dim">
            {state.data.plan.notes.split("\n").map((n, i) => (
              <li key={i} className="flex gap-2">
                <Scissors className="mt-0.5 size-3 shrink-0 text-accent" aria-hidden />
                {n}
              </li>
            ))}
          </ul>
        )}

        {latest && !planning && <RenderCard projectId={project.id} render={latest} live={render[latest.id]} filename={project.name} />}

        {!busy && !archived && (
          <>
            <button type="button" onClick={() => setOpen((x) => !x)} className="flex w-full items-center justify-between text-[13px] font-semibold text-dim">
              Sozlamalar
              <ChevronDown className={cx("size-4 transition-transform", open && "rotate-180")} aria-hidden />
            </button>
            {open && (
              <div className="space-y-3">
                <div>
                  <p className="label mb-1.5">Davomiylik</p>
                  <div className="flex flex-wrap gap-2">
                    {AUTO_EDIT_DURATIONS.map((d) => (
                      <Chip key={String(d)} active={duration === d} onClick={() => setDuration(d)}>
                        {durationLabel(d)}
                      </Chip>
                    ))}
                  </div>
                </div>
                <div>
                  <p className="label mb-1.5">Subtitr</p>
                  <div className="flex flex-wrap gap-2">
                    {CAPTIONS.map((c) => (
                      <Chip key={c} active={captions === c} onClick={() => setCaptions(c)}>
                        {c === "off" ? "Yo'q" : CAPTION_STYLE_LABEL[c].title}
                      </Chip>
                    ))}
                  </div>
                </div>
                <div>
                  <p className="label mb-1.5">Ko'rinish</p>
                  <div className="flex flex-wrap gap-2">
                    {(Object.keys(ENHANCE_PROFILE_LABEL) as Profile[]).map((p) => (
                      <Chip key={p} active={profile === p} onClick={() => setProfile(p)}>
                        {ENHANCE_PROFILE_LABEL[p].title}
                      </Chip>
                    ))}
                  </div>
                </div>
                <div>
                  <p className="label mb-1.5">Ovoz balandligi</p>
                  <div className="flex flex-wrap gap-2">
                    {(Object.keys(LOUDNESS_TARGET_LABEL) as Loudness[]).map((t) => (
                      <Chip key={t} active={loudness === t} onClick={() => setLoudness(t)}>
                        {LOUDNESS_TARGET_LABEL[t]}
                      </Chip>
                    ))}
                  </div>
                </div>
                <div>
                  <p className="label mb-1.5">Shovqin tozalash</p>
                  <div className="flex flex-wrap gap-2">
                    {(Object.keys(DENOISE) as Denoise[]).map((d) => (
                      <Chip key={d} active={denoise === d} onClick={() => setDenoise(d)}>
                        {DENOISE[d]}
                      </Chip>
                    ))}
                  </div>
                  <p className="mt-1 text-[11px] text-faint">Fon musiqasi bo'lsa «Yengil» yoki «O'chiq» — kuchli tozalash musiqani ham bosadi.</p>
                </div>
                <div className="grid gap-2">
                  <input
                    value={title}
                    onChange={(e) => setTitle(e.target.value.slice(0, 60))}
                    placeholder="Sarlavha (ixtiyoriy)"
                    className="h-10 rounded-xl border border-line bg-s1 px-3 text-sm outline-none focus:border-accent"
                  />
                  <input
                    value={cta}
                    onChange={(e) => setCta(e.target.value.slice(0, 40))}
                    placeholder="Oxirida chaqiriq, masalan «Obuna bo'ling» (ixtiyoriy)"
                    className="h-10 rounded-xl border border-line bg-s1 px-3 text-sm outline-none focus:border-accent"
                  />
                </div>
                <div className="divide-y divide-line">
                  <Toggle on={cutPauses} onChange={setCutPauses}>
                    Pauzalarni kesish
                  </Toggle>
                  <Toggle on={deliver} onChange={setDeliver}>
                    Tayyor bo'lgach Telegramga yuborish
                  </Toggle>
                </div>
              </div>
            )}
            <Button className="w-full" size="lg" variant="primary" loading={run.isPending} icon={state.data?.plan ? <Wand2 className="size-4" /> : <Sparkles className="size-4" />} onClick={() => run.mutate()}>
              {state.data?.plan ? "Qayta montaj (yangi versiya)" : "Tez montaj"}
            </Button>
            {run.isError && <ErrorNote>{(run.error as Error).message}</ErrorNote>}
          </>
        )}
      </Card>
    </div>
  );
}
