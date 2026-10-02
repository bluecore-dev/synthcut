import type { EventEnvelope } from "../api/client";
import { formatClock } from "../services/format";
import { cx } from "./ui";

const LEVEL_DOT: Record<string, string> = {
  debug: "bg-faint",
  info: "bg-accent",
  warning: "bg-warn",
  error: "bg-err",
};

export function ActivityLog({
  events,
  limit,
  newestFirst = true,
}: {
  events: EventEnvelope[];
  limit?: number;
  newestFirst?: boolean;
}) {
  const ordered = newestFirst ? [...events].reverse() : events;
  const shown = limit ? ordered.slice(0, limit) : ordered;
  if (!shown.length) return <p className="px-4 py-6 text-center text-sm text-faint">Hali faoliyat yo'q</p>;
  return (
    <ul className="divide-y divide-line/60 font-mono text-[12px] leading-relaxed">
      {shown.map((ev) => (
        <li key={ev.id ?? `${ev.type}-${ev.created_at}`} className="flex gap-2.5 px-4 py-2">
          <span className="tabular shrink-0 text-faint">{formatClock(ev.created_at)}</span>
          <span className={cx("mt-[7px] size-1.5 shrink-0 rounded-full", LEVEL_DOT[ev.level] ?? "bg-faint")} aria-hidden />
          <span className={cx("min-w-0 break-words", ev.level === "error" ? "text-err" : ev.level === "warning" ? "text-warn" : "text-dim")}>
            {ev.message}
          </span>
        </li>
      ))}
    </ul>
  );
}
