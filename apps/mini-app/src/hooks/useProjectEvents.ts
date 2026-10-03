import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { api, unwrap, type EventEnvelope } from "../api/client";
import { openEventStream, type StreamState } from "../services/sse";

export interface RemoteUploadProgress {
  bytes: number;
  size: number;
  at: number;
}

const MAX_EVENTS = 500;

/** Activity log + live stream for one project; refreshes server state as events arrive. */
export function useProjectEvents(projectId: string) {
  const qc = useQueryClient();
  const [events, setEvents] = useState<EventEnvelope[]>([]);
  const [remoteUploads, setRemoteUploads] = useState<Record<string, RemoteUploadProgress>>({});
  const [ingest, setIngest] = useState<Record<string, { progress: number; step: string }>>({});
  const [stream, setStream] = useState<StreamState>("connecting");
  const pending = useRef<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    let close = () => {};

    const refresh = () => {
      if (pending.current) return;
      pending.current = window.setTimeout(() => {
        pending.current = null;
        void qc.invalidateQueries({ queryKey: ["project", projectId] });
        void qc.invalidateQueries({ queryKey: ["assets", projectId] });
        void qc.invalidateQueries({ queryKey: ["jobs", projectId] });
        void qc.invalidateQueries({ queryKey: ["projects"] });
      }, 500);
    };

    const onEvent = (ev: EventEnvelope) => {
      if (ev.id == null) {
        if (ev.type === "job.progress") {
          const d = ev.data as { asset_id?: string; progress?: number };
          if (d.asset_id) setIngest((prev) => ({ ...prev, [d.asset_id!]: { progress: d.progress ?? 0, step: ev.message } }));
        }
        if (ev.type === "upload.progress") {
          const d = ev.data as { asset_id?: string; bytes?: number; size?: number };
          if (d.asset_id) {
            setRemoteUploads((prev) => ({ ...prev, [d.asset_id!]: { bytes: d.bytes ?? 0, size: d.size ?? 0, at: Date.now() } }));
          }
        }
        return;
      }
      setEvents((prev) => {
        if (prev.some((e) => e.id === ev.id)) return prev;
        const next = [...prev, ev].sort((a, b) => (a.id ?? 0) - (b.id ?? 0));
        return next.length > MAX_EVENTS ? next.slice(-MAX_EVENTS) : next;
      });
      refresh();
    };

    (async () => {
      try {
        const page = await unwrap(
          api.GET("/api/v1/projects/{project_id}/events", { params: { path: { project_id: projectId }, query: { limit: 200 } } }),
        );
        if (cancelled) return;
        setEvents(page.items);
        const lastId = page.items.length ? (page.items[page.items.length - 1]!.id ?? 0) : 0;
        close = openEventStream(projectId, lastId, onEvent, setStream);
      } catch {
        if (!cancelled) setStream("retrying");
      }
    })();

    return () => {
      cancelled = true;
      close();
      if (pending.current) window.clearTimeout(pending.current);
      pending.current = null;
    };
  }, [projectId, qc]);

  return { events, remoteUploads, ingest, stream };
}
