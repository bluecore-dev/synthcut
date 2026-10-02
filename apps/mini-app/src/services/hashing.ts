import { md5 } from "hash-wasm";

function hexToBase64(hex: string): string {
  let binary = "";
  for (let i = 0; i < hex.length; i += 2) binary += String.fromCharCode(parseInt(hex.slice(i, i + 2), 16));
  return btoa(binary);
}

/** MD5 of one upload part: hex (to compare with the storage ETag) and base64
 * (the Content-MD5 header the presigned URL is signed with). */
export async function md5Part(buffer: ArrayBuffer): Promise<{ hex: string; b64: string }> {
  const hex = await md5(new Uint8Array(buffer));
  return { hex, b64: hexToBase64(hex) };
}

function base64url(bytes: ArrayBuffer): string {
  let binary = "";
  for (const b of new Uint8Array(bytes)) binary += String.fromCharCode(b);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

/** Identifies "the same file picked again" so an interrupted upload resumes. */
export async function fileFingerprint(file: File): Promise<string> {
  const text = `${file.name}|${file.size}|${file.lastModified}`;
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return base64url(digest);
}
