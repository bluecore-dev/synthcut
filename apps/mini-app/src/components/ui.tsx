import { Loader2 } from "lucide-react";
import type { ButtonHTMLAttributes, ReactNode } from "react";
import { haptic } from "../telegram";

const cx = (...parts: (string | false | null | undefined)[]) => parts.filter(Boolean).join(" ");

type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";

const VARIANTS: Record<ButtonVariant, string> = {
  primary: "bg-brand text-white active:bg-brand-press disabled:opacity-50",
  secondary: "bg-s2 text-fg border border-line active:bg-line disabled:opacity-50",
  ghost: "text-dim active:bg-s2 disabled:opacity-40",
  danger: "bg-s2 text-err border border-line active:bg-line disabled:opacity-50",
};

export function Button({
  variant = "secondary",
  size = "md",
  loading = false,
  icon,
  className,
  children,
  onClick,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: ButtonVariant;
  size?: "sm" | "md" | "lg";
  loading?: boolean;
  icon?: ReactNode;
}) {
  const sizes = { sm: "h-8 px-3 text-[13px] rounded-lg gap-1.5", md: "h-10 px-4 text-sm rounded-xl gap-2", lg: "h-12 px-5 text-[15px] rounded-xl gap-2" };
  return (
    <button
      {...rest}
      disabled={rest.disabled || loading}
      onClick={(e) => {
        haptic.tap();
        onClick?.(e);
      }}
      className={cx(
        "inline-flex items-center justify-center font-semibold transition-colors select-none",
        sizes[size],
        VARIANTS[variant],
        className,
      )}
    >
      {loading ? <Loader2 className="size-4 animate-spin" aria-hidden /> : icon}
      {children}
    </button>
  );
}

export function Card({ className, children }: { className?: string; children: ReactNode }) {
  return <div className={cx("rounded-2xl border border-line bg-s1", className)}>{children}</div>;
}

export function SectionLabel({ children, right }: { children: ReactNode; right?: ReactNode }) {
  return (
    <div className="mb-2 flex items-center justify-between px-1">
      <h2 className="label">{children}</h2>
      {right}
    </div>
  );
}

type Tone = "neutral" | "accent" | "ok" | "warn" | "err" | "run";
const TONES: Record<Tone, string> = {
  neutral: "text-dim bg-s2 border-line",
  accent: "text-accent bg-accent/10 border-accent/25",
  ok: "text-ok bg-ok/10 border-ok/25",
  warn: "text-warn bg-warn/10 border-warn/25",
  err: "text-err bg-err/10 border-err/25",
  run: "text-run bg-run/10 border-run/25",
};

export function Badge({ tone = "neutral", children, className }: { tone?: Tone; children: ReactNode; className?: string }) {
  return (
    <span className={cx("inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-[11px] font-semibold leading-none", TONES[tone], className)}>
      {children}
    </span>
  );
}

export function ProgressBar({ value, tone = "accent", className }: { value: number; tone?: "accent" | "ok" | "run" | "warn" | "err"; className?: string }) {
  const fill = { accent: "bg-accent", ok: "bg-ok", run: "bg-run", warn: "bg-warn", err: "bg-err" }[tone];
  const pctValue = Math.max(0, Math.min(1, value)) * 100;
  return (
    <div
      className={cx("h-1.5 w-full overflow-hidden rounded-full bg-s2", className)}
      role="progressbar"
      aria-valuenow={Math.round(pctValue)}
      aria-valuemin={0}
      aria-valuemax={100}
    >
      <div className={cx("h-full rounded-full transition-[width] duration-300", fill)} style={{ width: `${pctValue}%` }} />
    </div>
  );
}

export function Spinner({ className }: { className?: string }) {
  return <Loader2 className={cx("size-5 animate-spin text-faint", className)} aria-label="Yuklanmoqda" />;
}

export function EmptyState({ icon, title, children }: { icon: ReactNode; title: string; children?: ReactNode }) {
  return (
    <div className="flex flex-col items-center px-6 py-12 text-center">
      <div className="mb-4 grid size-14 place-items-center rounded-2xl border border-line bg-s1 text-accent">{icon}</div>
      <p className="text-[15px] font-semibold text-fg">{title}</p>
      {children && <div className="mt-1.5 max-w-xs text-sm text-dim">{children}</div>}
    </div>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cx("pulse rounded-xl bg-s1", className)} />;
}

export function ErrorNote({ children }: { children: ReactNode }) {
  return <div className="rounded-xl border border-err/30 bg-err/10 px-3 py-2.5 text-sm text-err">{children}</div>;
}

export { cx };

export function Chip({ active, children, onClick }: { active: boolean; children: ReactNode; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={() => {
        haptic.select();
        onClick();
      }}
      className={cx(
        "h-9 rounded-lg border px-3 text-[13px] font-semibold transition-colors",
        active ? "border-accent/60 bg-accent/15 text-fg" : "border-line bg-s1 text-dim active:bg-s2",
      )}
    >
      {children}
    </button>
  );
}
