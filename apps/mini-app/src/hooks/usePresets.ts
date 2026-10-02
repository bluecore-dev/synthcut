import { useQuery } from "@tanstack/react-query";
import { api, unwrap, type PresetId, type Schemas } from "../api/client";

/** Output presets come from the server (single source of truth). */
export function usePresets() {
  const q = useQuery({ queryKey: ["presets"], queryFn: () => unwrap(api.GET("/api/v1/presets")), staleTime: Infinity });
  const byId = new Map<PresetId, Schemas["PresetOut"]>((q.data ?? []).map((p) => [p.id, p]));
  return { ...q, byId };
}

export function presetBadge(preset: Schemas["PresetOut"] | undefined, fallback: string): string {
  if (!preset) return fallback;
  return preset.family === "long" ? `${preset.aspect} · ${preset.height >= 2160 ? "4K" : `${preset.height}p`}` : preset.aspect;
}
