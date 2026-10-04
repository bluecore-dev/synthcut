import { useState } from "react";

/** Drag the divider to compare two stills of the same frame. */
export function BeforeAfter({ before, after }: { before: string; after: string }) {
  const [split, setSplit] = useState(50);
  return (
    <div className="relative select-none overflow-hidden rounded-xl border border-line bg-black">
      <img src={after} alt="Keyin" className="block w-full" draggable={false} />
      <img src={before} alt="Oldin" className="absolute inset-0 h-full w-full object-cover" style={{ clipPath: `inset(0 ${100 - split}% 0 0)` }} draggable={false} />
      <div className="pointer-events-none absolute inset-y-0 w-0.5 bg-white/90 shadow" style={{ left: `${split}%` }} />
      <span className="absolute left-2 top-2 rounded bg-black/60 px-1.5 py-0.5 text-[11px] font-semibold text-white">Oldin</span>
      <span className="absolute right-2 top-2 rounded bg-black/60 px-1.5 py-0.5 text-[11px] font-semibold text-white">Keyin</span>
      <input
        type="range"
        min={0}
        max={100}
        value={split}
        onChange={(e) => setSplit(Number(e.target.value))}
        aria-label="Taqqoslash"
        className="absolute inset-0 h-full w-full cursor-ew-resize opacity-0"
      />
    </div>
  );
}
