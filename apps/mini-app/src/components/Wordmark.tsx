export function Wordmark() {
  return (
    <div className="flex items-center gap-2" aria-label="SynthCut">
      <svg viewBox="0 0 24 24" className="size-6" aria-hidden>
        <rect x="1" y="1" width="22" height="22" rx="6" fill="#5b47f0" />
        <path d="M7 15.5 L11 8.5 L13 12 L15 9.5 L17.5 15.5" fill="none" stroke="#fff" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
        <path d="M6.5 17.5 H17.5" stroke="#9b8cff" strokeWidth="1.8" strokeLinecap="round" />
      </svg>
      <span className="text-[13px] font-bold tracking-[0.22em] text-fg">SYNTHCUT</span>
    </div>
  );
}
