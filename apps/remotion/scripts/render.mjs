// Renders the "Overlay" composition to a transparent ProRes 4444 .mov.
// Measured (300 frames, 720×1280): frame capture 8 s, ProRes 4444 11 s,
// VP8 + alpha 63 s — the layer is mostly transparent, so ProRes stays small
// (~1.4 MB/s) and FFmpeg decodes its alpha natively. Called by the worker:
//   node scripts/render.mjs <props.json> <out.mov> <bundle dir> [concurrency]
// Prints one JSON line per progress update ({"progress": 0.42}) on stdout.
import { readFileSync } from "node:fs";
import { renderMedia, selectComposition } from "@remotion/renderer";

const [propsPath, outPath, serveUrl, concurrency = "2"] = process.argv.slice(2);
if (!propsPath || !outPath || !serveUrl) {
  console.error("usage: render.mjs <props.json> <out.mov> <bundle dir> [concurrency]");
  process.exit(2);
}
const inputProps = JSON.parse(readFileSync(propsPath, "utf8"));
const id = process.env.SYNTHCUT_COMPOSITION ?? "Overlay";
const chromiumOptions = process.env.SYNTHCUT_GL ? { gl: process.env.SYNTHCUT_GL } : {};

const composition = await selectComposition({ serveUrl, id, inputProps, chromiumOptions, logLevel: "warn" });
let last = -1;
await renderMedia({
  composition,
  serveUrl,
  codec: "prores",
  proResProfile: "4444",
  imageFormat: "png",
  pixelFormat: "yuva444p10le",
  outputLocation: outPath,
  inputProps,
  concurrency: Number(concurrency),
  chromiumOptions,
  logLevel: "warn",
  timeoutInMilliseconds: 120_000,
  onProgress: ({ progress }) => {
    const p = Math.floor(progress * 100);
    if (p !== last) {
      last = p;
      console.log(JSON.stringify({ progress: Math.round(progress * 1000) / 1000 }));
    }
  },
});
console.log(JSON.stringify({ done: outPath, frames: composition.durationInFrames }));
