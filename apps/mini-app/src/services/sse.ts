import { currentToken, type EventEnvelope } from "../api/client";

// fetch-based SSE: EventSource cannot send an Authorization header, and a
// token in the URL would end up in access logs.

export type StreamState = "connecting" | "live" | "retrying";

export function openEventStream(
  projectId: string,
  initialAfterId: number,
  onEvent: (event: EventEnvelope) => void,
  onState: (state: StreamState) => void,
): () => void {
  let lastId = initialAfterId;
  let closed = false;
  let controller: AbortController | null = null;
  let attempt = 0;

  const run = async () => {
    while (!closed) {
      controller = new AbortController();
      onState(attempt === 0 ? "connecting" : "retrying");
      try {
        const res = await fetch(`/api/v1/projects/${projectId}/events/stream?after_id=${lastId}`, {
          headers: { Authorization: `Bearer ${currentToken() ?? ""}`, Accept: "text/event-stream" },
          signal: controller.signal,
          cache: "no-store",
        });
        if (!res.ok || !res.body) throw new Error(`stream ${res.status}`);
        onState("live");
        attempt = 0;
        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        for (;;) {
          const { value, done } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          let cut: number;
          while ((cut = buffer.indexOf("\n\n")) >= 0) {
            const frame = buffer.slice(0, cut);
            buffer = buffer.slice(cut + 2);
            let data = "";
            for (const line of frame.split("\n")) {
              if (line.startsWith("data:")) data += line.slice(5).trim();
              else if (line.startsWith("id:")) lastId = Math.max(lastId, Number(line.slice(3).trim()) || 0);
            }
            if (data) {
              try {
                onEvent(JSON.parse(data) as EventEnvelope);
              } catch {
                /* a malformed frame is skipped, the stream continues */
              }
            }
          }
        }
      } catch {
        if (closed) return;
      }
      if (closed) return;
      attempt += 1;
      onState("retrying");
      await new Promise((r) => setTimeout(r, Math.min(15_000, 1000 * 2 ** Math.min(attempt, 4))));
    }
  };
  void run();
  return () => {
    closed = true;
    controller?.abort();
  };
}
