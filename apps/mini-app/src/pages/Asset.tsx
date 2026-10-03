import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Captions, Download, Play, RefreshCw } from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router";
import { api, unwrap, type AssetDetail, type Schemas, type TranscriptSummary } from "../api/client";
import { colorTone } from "../components/AssetList";
import { TranscriptView, languageNote } from "../components/TranscriptView";
import { Badge, Button, Card, Chip, ErrorNote, ProgressBar, SectionLabel, Skeleton } from "../components/ui";
import { useBackButton } from "../hooks/useBackButton";
import { useProjectEvents, type JobProgress } from "../hooks/useProjectEvents";
import { formatBytes, formatDuration, pct } from "../services/format";
import { stableUrl } from "../services/urlcache";
import { ASSET_STATUS_LABEL, LANGUAGE_LABEL, TRANSCRIPT_STATUS_LABEL } from "../strings";
import { confirmDialog, downloadFile, haptic } from "../telegram";

type File = AssetDetail["files"][number];

function Row({ label, children }: { label: string; children: ReactNode }) {
  if (children === null || children === undefined || children === "") return null;
  return (
    <div className="flex justify-between gap-4 px-4 py-2.5 text-[13px]">
      <span className="shrink-0 text-faint">{label}</span>
      <span className="tabular min-w-0 text-right text-fg [overflow-wrap:anywhere]">{children}</span>
    </div>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div>
      <SectionLabel>{title}</SectionLabel>
      <Card className="divide-y divide-line">{children}</Card>
    </div>
  );
}

const kbps = (bps: number | null | undefined) => (bps ? `${(bps / 1_000_000).toFixed(bps > 10_000_000 ? 0 : 1)} Mbit/s` : null);

function Filmstrip({ file, src, onSeek }: { file: File; src: string | undefined; onSeek: (t: number) => void }) {
  const tiles = Number(file.metadata.tiles ?? 1);
  const interval = Number(file.metadata.interval ?? 0);
  return (
    <div className="no-scrollbar overflow-x-auto rounded-xl border border-line bg-black">
      <div className="relative" style={{ width: file.width ?? undefined, height: file.height ?? undefined }}>
        <img src={src} alt="" className="block max-w-none" draggable={false} />
        <div className="absolute inset-0 flex">
          {Array.from({ length: tiles }, (_, i) => (
            <button
              type="button"
              key={i}
              aria-label={`${formatDuration(i * interval)} ga o'tish`}
              className="h-full flex-1 border-r border-black/40 active:bg-white/20"
              onClick={() => onSeek(i * interval)}
            />
          ))}
        </div>
      </div>
    </div>
  );
}

type Language = Schemas["ProjectLanguage"];
const LANGUAGES = Object.keys(LANGUAGE_LABEL) as Language[];
const ACTIVE = new Set(["queued", "running"]);

function Speech({
  assetId,
  summary,
  live,
  currentTime,
  onSeek,
  filename,
}: {
  assetId: string;
  summary: TranscriptSummary | null | undefined;
  live: JobProgress | undefined;
  currentTime: number | null;
  onSeek?: (t: number) => void;
  filename: string;
}) {
  const qc = useQueryClient();
  const [language, setLanguage] = useState<Language>(() => (summary?.requested_language as Language | undefined) ?? "auto");
  const run = useMutation({
    mutationFn: () =>
      unwrap(api.POST("/api/v1/assets/{asset_id}/transcribe", { params: { path: { asset_id: assetId } }, body: { language } })),
    onSuccess: () => {
      haptic.success();
      void qc.invalidateQueries({ queryKey: ["asset", assetId] });
    },
    onError: () => haptic.error(),
  });
  const active = summary && ACTIVE.has(summary.status);
  const stats = summary?.status === "done"
    ? [
        languageNote(summary),
        `${summary.word_count ?? 0} so'z`,
        summary.speech_sec != null ? `nutq ${formatDuration(summary.speech_sec)}` : null,
      ].filter(Boolean)
    : [];
  return (
    <div>
      <SectionLabel right={summary ? <span className="text-xs text-faint">{TRANSCRIPT_STATUS_LABEL[summary.status]}</span> : null}>Nutq</SectionLabel>
      <Card className="divide-y divide-line">
        {summary?.status === "done" && (
          <div className="flex items-center gap-2 px-4 py-3">
            <p className="min-w-0 flex-1 text-[13px] text-dim">{stats.join(" · ")}</p>
            {summary.subtitles_srt && (
              <Button
                size="sm"
                variant="ghost"
                icon={<Download className="size-4" />}
                onClick={() => downloadFile(summary.subtitles_srt!.url, `${filename.replace(/\.[^.]+$/, "")}.srt`)}
              >
                SRT
              </Button>
            )}
          </div>
        )}
        {active && (
          <div className="px-4 py-3">
            <ProgressBar value={live?.progress ?? 0} tone="run" />
            <p className="mt-1.5 text-xs text-run">
              {summary.status === "queued" ? "Navbatda — avval barcha fayllar tahlil qilinadi" : `Whisper · ${live ? pct(live.progress) : "boshlanmoqda"}`}
            </p>
            <p className="mt-1 text-[11px] text-faint">Server CPU'da ishlaydi: odatda video davomiyligidan uzoqroq vaqt oladi.</p>
          </div>
        )}
        {summary?.status === "failed" && summary.error && (
          <div className="px-4 py-3">
            <ErrorNote>{summary.error}</ErrorNote>
          </div>
        )}
        {summary?.status === "done" && (
          <TranscriptView assetId={assetId} version={summary.finished_at} currentTime={currentTime} onSeek={onSeek} />
        )}
        {!active && (
          <div className="space-y-3 px-4 py-3">
            <div className="flex flex-wrap gap-2">
              {LANGUAGES.map((l) => (
                <Chip key={l} active={language === l} onClick={() => setLanguage(l)}>
                  {LANGUAGE_LABEL[l]}
                </Chip>
              ))}
            </div>
            <Button
              className="w-full"
              loading={run.isPending}
              icon={summary ? <RefreshCw className="size-4" /> : <Captions className="size-4" />}
              onClick={async () => {
                if (summary?.status === "done" && !(await confirmDialog("Mavjud transkript yangisiga almashtiriladi. Davom etilsinmi?"))) return;
                run.mutate();
              }}
            >
              {summary ? "Qayta matnga o'girish" : "Matnga o'girish"}
            </Button>
            {run.isError && <ErrorNote>{(run.error as Error).message}</ErrorNote>}
          </div>
        )}
      </Card>
    </div>
  );
}

export function AssetPage() {
  const { id = "", assetId = "" } = useParams();
  const [params] = useSearchParams();
  useBackButton(`/p/${id}?tab=assets`);
  const video = useRef<HTMLVideoElement>(null);
  const audio = useRef<HTMLAudioElement>(null);
  const [time, setTime] = useState<number | null>(null);
  const navigate = useNavigate();
  const qc = useQueryClient();
  const { events, speech } = useProjectEvents(id);
  const reingest = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/assets/{asset_id}/reingest", { params: { path: { asset_id: assetId } } })),
    onSuccess: () => {
      haptic.success();
      void qc.invalidateQueries({ queryKey: ["asset", assetId] });
      void qc.invalidateQueries({ queryKey: ["assets", id] });
      navigate(`/p/${id}?tab=assets`, { replace: true });
    },
    onError: () => haptic.error(),
  });
  const q = useQuery({
    queryKey: ["asset", assetId],
    queryFn: () => unwrap(api.GET("/api/v1/assets/{asset_id}", { params: { path: { asset_id: assetId } } })),
    staleTime: 10 * 60_000,
    // The live stream drives updates; polling only covers a dropped stream while work is pending.
    refetchInterval: (query) => (ACTIVE.has(query.state.data?.transcript?.status ?? "") ? 15_000 : false),
  });
  const lastEvent = events[events.length - 1];
  useEffect(() => {
    const d = lastEvent?.data as { asset_id?: string } | undefined;
    if (d?.asset_id === assetId) void qc.invalidateQueries({ queryKey: ["asset", assetId] });
  }, [lastEvent, assetId, qc]);
  const startAt = Number(params.get("t") ?? "");

  if (q.isPending) {
    return (
      <div className="mx-auto max-w-xl space-y-3 px-4 pt-4">
        <Skeleton className="h-8 w-2/3" />
        <Skeleton className="aspect-video" />
        <Skeleton className="h-48" />
      </div>
    );
  }
  if (q.isError) {
    return (
      <div className="mx-auto max-w-xl px-4 pt-6">
        <ErrorNote>{(q.error as Error).message}</ErrorNote>
      </div>
    );
  }
  const a = q.data;
  const files = Object.fromEntries(a.files.map((f) => [f.kind, f])) as Record<string, File | undefined>;
  const info = a.media_info;
  const v = info?.video;
  const camera = info?.camera ?? {};
  const proxy = files.proxy_720p;
  const poster = stableUrl(`${a.id}:poster`, a.thumbnail);
  const vtt = a.transcript?.subtitles_vtt ? stableUrl(`${a.id}:vtt:${a.transcript.finished_at}`, a.transcript.subtitles_vtt) : undefined;
  const seek = (t: number) => {
    haptic.select();
    const player = video.current ?? audio.current;
    if (!player) return;
    player.currentTime = t;
    void player.play().catch(() => undefined);
  };
  const onTime = (e: { currentTarget: HTMLMediaElement }) => setTime(e.currentTarget.currentTime);
  const onReady = (e: { currentTarget: HTMLMediaElement }) => {
    if (Number.isFinite(startAt) && startAt > 0) e.currentTarget.currentTime = startAt;
  };

  return (
    <div className="mx-auto max-w-xl space-y-5 px-4 pb-12 pt-4">
      <header>
        <h1 className="break-words text-lg font-bold">{a.original_filename}</h1>
        <div className="mt-2 flex flex-wrap gap-1.5">
          <Badge tone={a.status === "ready" ? "ok" : a.status === "failed" ? "err" : "run"}>{ASSET_STATUS_LABEL[a.status]}</Badge>
          {a.color_label && <Badge tone={colorTone(a.color_profile)}>{a.color_label}</Badge>}
          {a.width && a.height && <Badge>{`${a.width}×${a.height}`}</Badge>}
          {a.fps && <Badge>{`${Math.round(a.fps * 100) / 100} fps`}</Badge>}
          {a.duration_sec && <Badge>{formatDuration(a.duration_sec)}</Badge>}
        </div>
      </header>

      {a.error && <ErrorNote>{a.error}</ErrorNote>}

      {proxy && (
        <div className="overflow-hidden rounded-2xl border border-line bg-black">
          <video
            ref={video}
            src={stableUrl(`${a.id}:proxy`, proxy.url)}
            poster={poster}
            controls
            playsInline
            preload="metadata"
            className="mx-auto max-h-[60vh] w-full"
            style={proxy.width && proxy.height ? { aspectRatio: `${proxy.width} / ${proxy.height}` } : undefined}
            onTimeUpdate={onTime}
            onLoadedMetadata={onReady}
          >
            {vtt && <track kind="subtitles" src={vtt} srcLang={a.transcript?.language ?? "und"} label="Transkript" default />}
          </video>
          <p className="border-t border-line px-3 py-2 text-[11px] text-faint">
            Proxy {proxy.width}×{proxy.height} · {String(proxy.metadata.color ?? "")}
          </p>
        </div>
      )}
      {files.audio_proxy && (
        <audio
          ref={audio}
          controls
          preload="metadata"
          src={stableUrl(`${a.id}:audio`, files.audio_proxy.url)}
          className="w-full"
          onTimeUpdate={onTime}
          onLoadedMetadata={onReady}
        />
      )}
      {files.preview && (
        <img src={stableUrl(`${a.id}:preview`, files.preview.url)} alt="" className="w-full rounded-2xl border border-line" />
      )}

      {files.sprite && proxy && (
        <div>
          <SectionLabel>Filmstrip</SectionLabel>
          <Filmstrip file={files.sprite} src={stableUrl(`${a.id}:sprite`, files.sprite.url)} onSeek={seek} />
        </div>
      )}

      {a.shots.length > 0 && (
        <div>
          <SectionLabel right={<span className="text-xs text-faint">{a.shots.length}</span>}>Kadr kesimlari (shots)</SectionLabel>
          <div className="flex flex-wrap gap-2">
            {a.shots.map((s) => (
              <button
                type="button"
                key={s.index}
                onClick={() => seek(s.start)}
                className="tabular inline-flex items-center gap-1.5 rounded-lg border border-line bg-s1 px-2.5 py-1.5 text-xs text-dim active:bg-s2"
              >
                <Play className="size-3 text-accent" aria-hidden />
                {s.index + 1} · {formatDuration(s.start)}–{formatDuration(s.end)}
              </button>
            ))}
          </div>
        </div>
      )}

      {a.status === "ready" && a.has_audio && (
        <Speech
          key={a.transcript?.finished_at ?? a.transcript?.status ?? "none"}
          assetId={a.id}
          summary={a.transcript}
          live={speech[a.id]}
          currentTime={time}
          onSeek={proxy || files.audio_proxy ? seek : undefined}
          filename={a.original_filename}
        />
      )}

      {v && (
        <Section title="Video">
          <Row label="Kodek">{[v.codec?.toUpperCase(), v.profile].filter(Boolean).join(" · ")}</Row>
          <Row label="O'lcham">{v.width === v.display_width && v.height === v.display_height ? `${v.width}×${v.height}` : `${v.width}×${v.height} → ${v.display_width}×${v.display_height}`}</Row>
          <Row label="Aylantirish">{v.rotation ? `${v.rotation}°` : null}</Row>
          <Row label="Kadr tezligi">{v.fps ? `${v.fps} fps${v.vfr ? " (o'zgaruvchan)" : ""}` : null}</Row>
          <Row label="Bit / chroma">{[v.bit_depth ? `${v.bit_depth}-bit` : null, v.chroma ? `4:${v.chroma.slice(1, 2)}:${v.chroma.slice(2)}` : null, v.pix_fmt].filter(Boolean).join(" · ")}</Row>
          <Row label="Bitreyt">{kbps(v.bitrate ?? info?.bitrate)}</Row>
        </Section>
      )}

      {info?.color && (
        <Section title="Rang">
          <Row label="Profil">{`${info.color.label} (${info.color.confidence === "high" ? "aniq" : info.color.confidence === "medium" ? "ehtimol" : "taxmin"})`}</Row>
          <Row label="Primaries / transfer / matrix">{[v?.color_primaries, v?.color_transfer, v?.color_space].map((x) => x ?? "—").join(" / ")}</Row>
          <Row label="Diapazon">{v?.color_range === "pc" ? "full" : v?.color_range === "tv" ? "limited" : null}</Row>
          <Row label="Izoh">{info.color.log ? "Log asl holicha saqlanadi; rang transformi Phase 8 da" : info.color.hdr ? "HDR asl holicha saqlanadi" : null}</Row>
        </Section>
      )}

      {info?.audio && (
        <Section title="Audio">
          <Row label="Kodek">{[info.audio.codec?.toUpperCase(), info.audio.profile].filter(Boolean).join(" · ")}</Row>
          <Row label="Kanal / chastota">{[info.audio.channel_layout ?? (info.audio.channels ? `${info.audio.channels} ch` : null), info.audio.sample_rate ? `${info.audio.sample_rate / 1000} kHz` : null].filter(Boolean).join(" · ")}</Row>
          <Row label="Balandlik">{info.loudness?.integrated_lufs != null ? `${info.loudness.integrated_lufs} LUFS` : null}</Row>
          <Row label="True peak">{info.loudness?.true_peak_dbfs != null ? `${info.loudness.true_peak_dbfs} dBFS` : null}</Row>
          <Row label="Dinamik diapazon">{info.loudness?.lra_lu != null ? `${info.loudness.lra_lu} LU` : null}</Row>
        </Section>
      )}

      {Object.keys(camera).length > 0 && (
        <Section title="Kamera">
          <Row label="Qurilma">{[camera.make, camera.model].filter(Boolean).join(" ")}</Row>
          <Row label="Dastur">{camera.software}</Row>
          <Row label="Linza">{camera.lens}</Row>
          <Row label="Yozilgan">{camera.created}</Row>
        </Section>
      )}

      <Section title="Fayl">
        <Row label="Hajm">{formatBytes(a.size_bytes)}</Row>
        <Row label="Konteyner">{info?.container?.split(",")[0]}</Row>
        <Row label="SHA-256">{a.sha256 ? <span className="font-mono text-[11px]">{a.sha256}</span> : null}</Row>
        <Row label="Original">o'zgartirilmaydi (immutable)</Row>
      </Section>

      {(a.status === "ready" || a.status === "failed") && (
        <div>
          <Button
            className="w-full"
            loading={reingest.isPending}
            icon={<RefreshCw className="size-4" />}
            onClick={async () => {
              if (await confirmDialog("Fayl qayta tahlil qilinsinmi? Proxy va thumbnail'lar yangidan yaratiladi, original o'zgarmaydi.")) {
                reingest.mutate();
              }
            }}
          >
            Qayta tahlil qilish
          </Button>
          {reingest.isError && <ErrorNote>{(reingest.error as Error).message}</ErrorNote>}
        </div>
      )}
    </div>
  );
}
