import { useQuery } from "@tanstack/react-query";
import { Play } from "lucide-react";
import { useRef, type ReactNode } from "react";
import { useParams } from "react-router";
import { api, unwrap, type AssetDetail } from "../api/client";
import { colorTone } from "../components/AssetList";
import { Badge, Card, ErrorNote, SectionLabel, Skeleton } from "../components/ui";
import { useBackButton } from "../hooks/useBackButton";
import { formatBytes, formatDuration } from "../services/format";
import { stableUrl } from "../services/urlcache";
import { ASSET_STATUS_LABEL } from "../strings";
import { haptic } from "../telegram";

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

export function AssetPage() {
  const { id = "", assetId = "" } = useParams();
  useBackButton(`/p/${id}?tab=assets`);
  const video = useRef<HTMLVideoElement>(null);
  const q = useQuery({
    queryKey: ["asset", assetId],
    queryFn: () => unwrap(api.GET("/api/v1/assets/{asset_id}", { params: { path: { asset_id: assetId } } })),
    staleTime: 10 * 60_000,
  });

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
  const seek = (t: number) => {
    haptic.select();
    if (!video.current) return;
    video.current.currentTime = t;
    void video.current.play().catch(() => undefined);
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
          />
          <p className="border-t border-line px-3 py-2 text-[11px] text-faint">
            Proxy {proxy.width}×{proxy.height} · {String(proxy.metadata.color ?? "")}
          </p>
        </div>
      )}
      {files.audio_proxy && <audio controls preload="metadata" src={stableUrl(`${a.id}:audio`, files.audio_proxy.url)} className="w-full" />}
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
    </div>
  );
}
