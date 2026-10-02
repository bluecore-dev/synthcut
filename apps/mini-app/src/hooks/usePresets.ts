import { useQuery } from "@tanstack/react-query";
import { api, unwrap, type PresetId, type Schemas } from "../api/client";

/** Output presets come from the server (single source of truth). */
export function usePresets() {
  const q = useQuery({ queryKey: ["presets"], queryFn: () => unwrap(api.GET("/api/v1/presets")), staleTime: Infinity });
  const byId = new Map<PresetId, Schemas["PresetOut"]>((q.data ?? []).map((p) => [p.id, p]));
  return { ...q, byId };
}

/** Short badge text, or null until the presets have loaded (never the raw id). */
export function presetBadge(preset: Schemas["PresetOut"] | undefined): string | null {
  if (!preset) return null;
  return preset.family === "long" ? `${preset.aspect} · ${preset.height >= 2160 ? "4K" : `${preset.height}p`}` : preset.aspect;
}
