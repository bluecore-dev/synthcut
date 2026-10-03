import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate } from "react-router";
import { api, unwrap, type PresetId, type ProjectCreate, type Schemas } from "../api/client";
import { Button, Card, Chip, ErrorNote, SectionLabel, Skeleton, cx } from "../components/ui";
import { useBackButton } from "../hooks/useBackButton";
import { LANGUAGE_LABEL, LONG_DURATIONS, MODE_LABEL, SHORT_DURATIONS } from "../strings";
import { haptic } from "../telegram";

type Fps = ProjectCreate["fps"] & number;
const FPS_CHOICES: Fps[] = [24, 25, 30, 50, 60];
const MODES = Object.keys(MODE_LABEL) as Schemas["ProjectMode"][];
const LANGUAGES = Object.keys(LANGUAGE_LABEL) as Schemas["ProjectLanguage"][];


function AspectGlyph({ width, height }: { width: number; height: number }) {
  const scale = 22 / Math.max(width, height);
  return (
    <span className="grid size-7 place-items-center" aria-hidden>
      <span className="rounded-[3px] border-[1.5px] border-current" style={{ width: width * scale, height: height * scale }} />
    </span>
  );
}

function formatTarget(seconds: number) {
  return seconds < 60 ? `${seconds}s` : seconds % 60 === 0 ? `${seconds / 60} daq` : `${seconds}s`;
}

export function NewProject() {
  useBackButton("/");
  const navigate = useNavigate();
  const qc = useQueryClient();
  const presets = useQuery({ queryKey: ["presets"], queryFn: () => unwrap(api.GET("/api/v1/presets")), staleTime: Infinity });

  const [name, setName] = useState("");
  const [preset, setPreset] = useState<PresetId>("reels_9x16");
  const [fps, setFps] = useState<Fps>(30);
  const [target, setTarget] = useState<number | null>(60);
  const [mode, setMode] = useState<Schemas["ProjectMode"]>("auto");
  const [language, setLanguage] = useState<Schemas["ProjectLanguage"]>("auto");
  const [brief, setBrief] = useState("");

  const family = presets.data?.find((p) => p.id === preset)?.family ?? "short";
  const durations = family === "long" ? LONG_DURATIONS : SHORT_DURATIONS;

  const create = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST("/api/v1/projects", {
          body: {
            name: name.trim(),
            preset,
            fps,
            target_duration_sec: target,
            mode,
            language,
            brief: brief.trim() || null,
          },
        }),
      ),
    onSuccess: (project) => {
      haptic.success();
      void qc.invalidateQueries({ queryKey: ["projects"] });
      navigate(`/p/${project.id}?tab=assets`, { replace: true });
    },
    onError: () => haptic.error(),
  });

  return (
    <form
      className="mx-auto max-w-xl space-y-6 px-4 pb-32 pt-4"
      onSubmit={(e) => {
        e.preventDefault();
        if (name.trim()) create.mutate();
      }}
    >
      <h1 className="text-xl font-bold">Yangi loyiha</h1>

      <div>
        <SectionLabel>Nomi</SectionLabel>
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          maxLength={120}
          placeholder="Masalan: Kuzgi kolleksiya reel"
          className="h-12 w-full rounded-xl border border-line bg-s1 px-4 text-[15px] text-fg placeholder:text-faint focus:border-accent/60 focus:outline-none"
        />
      </div>

      <div>
        <SectionLabel>Format</SectionLabel>
        {presets.isPending ? (
          <Skeleton className="h-40" />
        ) : (
          <Card className="divide-y divide-line overflow-hidden">
            {presets.data?.map((p) => (
              <button
                type="button"
                key={p.id}
                onClick={() => {
                  haptic.select();
                  setPreset(p.id);
                  setTarget(p.family === "long" ? 600 : 60);
                }}
                className={cx("flex w-full items-center gap-3 px-4 py-3 text-left", preset === p.id ? "bg-accent/10 text-accent" : "text-dim active:bg-s2")}
              >
                <AspectGlyph width={p.width} height={p.height} />
                <span className="min-w-0 flex-1">
                  <span className={cx("block text-sm font-semibold", preset === p.id ? "text-fg" : "text-fg/90")}>{p.label}</span>
                  <span className="tabular block text-xs text-faint">
                    {p.width}×{p.height} · {p.aspect}
                  </span>
                </span>
                <span className={cx("size-4 rounded-full border-2", preset === p.id ? "border-accent bg-accent" : "border-line")} />
              </button>
            ))}
          </Card>
        )}
      </div>

      <div>
        <SectionLabel>Davomiylik</SectionLabel>
        <div className="flex flex-wrap gap-2">
          <Chip active={target === null} onClick={() => setTarget(null)}>
            Avto
          </Chip>
          {durations.map((d) => (
            <Chip key={d} active={target === d} onClick={() => setTarget(d)}>
              {formatTarget(d)}
            </Chip>
          ))}
        </div>
      </div>

      <div>
        <SectionLabel>Kadr tezligi</SectionLabel>
        <div className="flex flex-wrap gap-2">
          {FPS_CHOICES.map((f) => (
            <Chip key={f} active={fps === f} onClick={() => setFps(f)}>
              {f} fps
            </Chip>
          ))}
        </div>
      </div>

      <div>
        <SectionLabel>Rejim</SectionLabel>
        <div className="grid grid-cols-3 gap-2">
          {MODES.map((m) => (
            <button
              type="button"
              key={m}
              onClick={() => {
                haptic.select();
                setMode(m);
              }}
              className={cx(
                "rounded-xl border p-3 text-left",
                mode === m ? "border-accent/60 bg-accent/10" : "border-line bg-s1 active:bg-s2",
              )}
            >
              <span className="block text-sm font-semibold">{MODE_LABEL[m].title}</span>
              <span className="mt-0.5 block text-[11px] leading-snug text-dim">{MODE_LABEL[m].hint}</span>
            </button>
          ))}
        </div>
      </div>

      <div>
        <SectionLabel>Nutq tili</SectionLabel>
        <div className="flex flex-wrap gap-2">
          {LANGUAGES.map((l) => (
            <Chip key={l} active={language === l} onClick={() => setLanguage(l)}>
              {LANGUAGE_LABEL[l]}
            </Chip>
          ))}
        </div>
      </div>

      <div>
        <SectionLabel>Brief (ixtiyoriy)</SectionLabel>
        <textarea
          value={brief}
          onChange={(e) => setBrief(e.target.value)}
          maxLength={4000}
          rows={4}
          placeholder="Video nima haqida, uslub, kayfiyat, CTA…"
          className="w-full resize-none rounded-xl border border-line bg-s1 px-4 py-3 text-sm text-fg placeholder:text-faint focus:border-accent/60 focus:outline-none"
        />
      </div>

      {create.isError && <ErrorNote>{(create.error as Error).message}</ErrorNote>}

      <div className="fixed inset-x-0 bottom-0 border-t border-line bg-bg/90 px-4 pb-[max(12px,env(safe-area-inset-bottom))] pt-3 backdrop-blur">
        <div className="mx-auto max-w-xl">
          <Button type="submit" variant="primary" size="lg" className="w-full" loading={create.isPending} disabled={!name.trim()}>
            Loyihani yaratish
          </Button>
        </div>
      </div>
    </form>
  );
}
