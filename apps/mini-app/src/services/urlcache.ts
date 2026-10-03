// Presigned URLs change on every API call; re-rendering an <img> with a new
// URL for the same file would flash and re-download it. Keep the first URL
// for a file until it is close to expiring.

const cache = new Map<string, { url: string; expires: number }>();
const MARGIN_MS = 5 * 60_000;

export function stableUrl(key: string, signed: { url: string; expires_at: string } | null | undefined): string | undefined {
  if (!signed) return undefined;
  const hit = cache.get(key);
  if (hit && hit.expires - Date.now() > MARGIN_MS) return hit.url;
  cache.set(key, { url: signed.url, expires: Date.parse(signed.expires_at) });
  return signed.url;
}
