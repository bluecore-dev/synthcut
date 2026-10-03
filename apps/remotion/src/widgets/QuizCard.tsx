import { spring, useCurrentFrame, useVideoConfig } from "remotion";
import type { QuizCardProps } from "../generated/types";
import { Animated } from "../lib/anim";
import { place } from "../lib/layout";
import { accentOf, useTheme, useUnits } from "../lib/theme";
import { cardStyle, Icon, type WidgetProps } from "./common";

const LETTERS = ["A", "B", "C", "D"];

export function QuizCard({ props, durationInFrames }: WidgetProps<QuizCardProps>) {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const { theme, safe } = useTheme();
  const { width, height, vmin, portrait } = useUnits();
  const accent = accentOf(props, theme);
  const revealFrame = props.reveal_at != null ? Math.round(props.reveal_at * fps) : null;
  const revealed = props.correct_index != null && revealFrame != null && frame >= revealFrame;
  return (
    <div style={place("center", safe, width, height)}>
      <Animated enter={props.enter} exit={props.exit} durationInFrames={durationInFrames} vmin={vmin}>
        <div style={cardStyle(vmin, { width: portrait ? width * 0.82 : width * 0.5, padding: vmin * 3.2 })}>
          <div style={{ fontWeight: 800, fontSize: vmin * 4.2, lineHeight: 1.2, marginBottom: vmin * 2.4 }}>{props.question}</div>
          {props.options.map((option, i) => {
            const appear = spring({ frame: frame - Math.round((0.25 + i * 0.12) * fps), fps, config: { damping: 16 }, durationInFrames: Math.round(0.4 * fps) });
            const correct = revealed && i === props.correct_index;
            const dim = revealed && !correct;
            return (
              <div key={i} style={{ display: "flex", alignItems: "center", gap: vmin * 1.6, marginTop: vmin * 1.2, padding: `${vmin * 1.4}px ${vmin * 1.8}px`, borderRadius: vmin * 1.6,
                background: correct ? "#22C55E" : "rgba(255,255,255,0.08)", border: `${vmin * 0.2}px solid ${correct ? "#22C55E" : "rgba(255,255,255,0.15)"}`,
                opacity: appear * (dim ? 0.45 : 1), transform: `translateX(${(1 - appear) * vmin * 6}px)` }}>
                <div style={{ width: vmin * 5, height: vmin * 5, borderRadius: "50%", background: correct ? "#fff" : accent, color: correct ? "#22C55E" : "#fff",
                  display: "flex", alignItems: "center", justifyContent: "center", fontWeight: 900, fontSize: vmin * 2.6 }}>
                  {correct ? <Icon name="check" size={vmin * 3.4} color="#22C55E" /> : LETTERS[i]}
                </div>
                <div style={{ fontWeight: 700, fontSize: vmin * 3.4 }}>{option}</div>
              </div>
            );
          })}
        </div>
      </Animated>
    </div>
  );
}
