// Renders the "Overlay" composition to a transparent PNG sequence
// (frame-0000.png …) that FFmpeg composites directly — no intermediate video.
// Measured on the VPS (300 frames, 1280×720, 2 cores): capture 26 s, capture +
// ProRes 4444 65 s, VP8 + alpha slower still. Called by the worker:
//   node scripts/render.mjs <props.json> <out dir> <bundle dir> [concurrency]
// Prints one JSON line per progress step ({"progress": 0.42}) on stdout.
import { readFileSync } from "node:fs";
import { availableParallelism } from "node:os";
import { renderFrames, selectComposition } from "@remotion/renderer";

/** Cores this process may use: the container's CPU quota (cgroup v2 cpu.max)
 *  when there is one — Remotion refuses a concurrency above it. */
function cores() {
  try {
    const [quota, period] = readFileSync("/sys/fs/cgroup/cpu.max", "utf8").trim().split(/\s+/);
    if (quota !== "max") return Math.max(1, Math.floor(Number(quota) / Number(period)));
  } catch {
    /* not Linux / no cgroup v2: fall through */
  }
  return availableParallelism();
}

const [propsPath, outDir, serveUrl, concurrency = "2"] = process.argv.slice(2);
if (!propsPath || !outDir || !serveUrl) {
  console.error("usage: render.mjs <props.json> <out dir> <bundle dir> [concurrency]");
  process.exit(2);
}
const inputProps = JSON.parse(readFileSync(propsPath, "utf8"));
const id = process.env.SYNTHCUT_COMPOSITION ?? "Overlay";
const chromiumOptions = process.env.SYNTHCUT_GL ? { gl: process.env.SYNTHCUT_GL } : {};

const composition = await selectComposition({ serveUrl, id, inputProps, chromiumOptions, logLevel: "warn" });
const total = composition.durationInFrames;
let last = -1;
await renderFrames({
  composition,
  serveUrl,
  inputProps,
  imageFormat: "png",
  outputDir: outDir,
  imageSequencePattern: "frame-[frame].[ext]",
  concurrency: Math.max(1, Math.min(Number(concurrency), cores())),
  chromiumOptions,
  logLevel: "warn",
  timeoutInMilliseconds: 120_000,
  onStart: () => {},
  onFrameUpdate: (rendered) => {
    const p = Math.floor((rendered / total) * 100);
    if (p !== last) {
      last = p;
      console.log(JSON.stringify({ progress: Math.round((rendered / total) * 1000) / 1000 }));
    }
  },
});
console.log(JSON.stringify({ done: outDir, frames: total }));
