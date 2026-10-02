// Pure-JS MD5: WebAssembly would need 'wasm-unsafe-eval' in the CSP, which
// older iOS WebViews do not understand (they would block hashing entirely).
import SparkMD5 from "spark-md5";

function hexToBase64(hex: string): string {
  let binary = "";
  for (let i = 0; i < hex.length; i += 2) binary += String.fromCharCode(parseInt(hex.slice(i, i + 2), 16));
  return btoa(binary);
}

/** MD5 of one upload part: hex (to compare with the storage ETag) and base64
 * (the Content-MD5 header the presigned URL is signed with). */
export async function md5Part(buffer: ArrayBuffer): Promise<{ hex: string; b64: string }> {
  const hex = SparkMD5.ArrayBuffer.hash(buffer);
  return { hex, b64: hexToBase64(hex) };
}

function base64url(bytes: ArrayBuffer): string {
  let binary = "";
  for (const b of new Uint8Array(bytes)) binary += String.fromCharCode(b);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

const EDGE = 1024 * 1024;

/** Identifies "the same file picked again" so an interrupted upload resumes.
 * Content-based (size + first and last MiB): the iOS Photos picker hands out a
 * new name (copy_<uuid>.mov) and lastModified on every pick, so metadata alone
 * would never match. Reads 2 MiB at most. */
export async function fileFingerprint(file: File): Promise<string> {
  const head = new Uint8Array(await file.slice(0, Math.min(EDGE, file.size)).arrayBuffer());
  const tail = file.size > EDGE ? new Uint8Array(await file.slice(Math.max(EDGE, file.size - EDGE)).arrayBuffer()) : new Uint8Array(0);
  const size = new TextEncoder().encode(`${file.size}:`);
  const joined = new Uint8Array(size.length + head.length + tail.length);
  joined.set(size, 0);
  joined.set(head, size.length);
  joined.set(tail, size.length + head.length);
  return base64url(await crypto.subtle.digest("SHA-256", joined));
}
