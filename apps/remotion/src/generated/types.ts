/* Generated from synthcut_timeline (python -m synthcut_timeline.schema) — do not edit. */

export interface MotionSchema {
  components: ComponentProps;
  overlay: OverlayProps;
}
/**
 * This interface was referenced by `MotionSchema`'s JSON-Schema
 * via the `definition` "ComponentProps".
 */
export interface ComponentProps {
  AbacusWidget: AbacusWidgetProps;
  AnimatedSubtitle: AnimatedSubtitleProps;
  CTA: CTAProps;
  Callout: CalloutProps;
  Chart: ChartProps;
  DocumentCard: DocumentCardProps;
  GamifiedTimer: GamifiedTimerProps;
  Highlight: HighlightProps;
  LogoReveal: LogoRevealProps;
  Notification: NotificationProps;
  PhoneMockup: PhoneMockupProps;
  ProgressBar: ProgressBarProps;
  QuizCard: QuizCardProps;
  ScoreCounter: ScoreCounterProps;
  TitleCard: TitleCardProps;
}
/**
 * This interface was referenced by `MotionSchema`'s JSON-Schema
 * via the `definition` "AbacusWidgetProps".
 */
export interface AbacusWidgetProps {
  accent: string | null;
  enter: "fade" | "pop" | "slide_up" | "slide_left" | "none";
  exit: "fade" | "slide_down" | "shrink" | "none";
  from_value: number | null;
  position: "top" | "bottom" | "center" | "top_left" | "top_right" | "bottom_left" | "bottom_right";
  rods: number;
  value: number;
}
/**
 * This interface was referenced by `MotionSchema`'s JSON-Schema
 * via the `definition` "AnimatedSubtitleProps".
 */
export interface AnimatedSubtitleProps {
  accent: string | null;
  enter: "fade" | "pop" | "slide_up" | "slide_left" | "none";
  exit: "fade" | "slide_down" | "shrink" | "none";
  /**
   * @maxItems 6
   */
  highlight:
    | []
    | [string]
    | [string, string]
    | [string, string, string]
    | [string, string, string, string]
    | [string, string, string, string, string]
    | [string, string, string, string, string, string];
  position: "top" | "center" | "bottom";
  text: string;
}
/**
 * This interface was referenced by `MotionSchema`'s JSON-Schema
 * via the `definition` "CTAProps".
 */
export interface CTAProps {
  accent: string | null;
  action: "subscribe" | "follow" | "like" | "comment" | "link";
  enter: "fade" | "pop" | "slide_up" | "slide_left" | "none";
  exit: "fade" | "slide_down" | "shrink" | "none";
  handle: string | null;
  position: "bottom" | "center";
  text: string;
}
/**
 * This interface was referenced by `MotionSchema`'s JSON-Schema
 * via the `definition` "CalloutProps".
 */
export interface CalloutProps {
  accent: string | null;
  enter: "fade" | "pop" | "slide_up" | "slide_left" | "none";
  exit: "fade" | "slide_down" | "shrink" | "none";
  side: "left" | "right" | "top" | "bottom";
  target: Point;
  text: string;
}
/**
 * This interface was referenced by `MotionSchema`'s JSON-Schema
 * via the `definition` "Point".
 */
export interface Point {
  x: number;
  y: number;
}
/**
 * This interface was referenced by `MotionSchema`'s JSON-Schema
 * via the `definition` "ChartProps".
 */
export interface ChartProps {
  accent: string | null;
  enter: "fade" | "pop" | "slide_up" | "slide_left" | "none";
  exit: "fade" | "slide_down" | "shrink" | "none";
  kind: "bar" | "line" | "pie";
  /**
   * @minItems 1
   * @maxItems 8
   */
  series:
    | [Datum]
    | [Datum, Datum]
    | [Datum, Datum, Datum]
    | [Datum, Datum, Datum, Datum]
    | [Datum, Datum, Datum, Datum, Datum]
    | [Datum, Datum, Datum, Datum, Datum, Datum]
    | [Datum, Datum, Datum, Datum, Datum, Datum, Datum]
    | [Datum, Datum, Datum, Datum, Datum, Datum, Datum, Datum];
  title: string | null;
  unit: string;
}
/**
 * This interface was referenced by `MotionSchema`'s JSON-Schema
 * via the `definition` "Datum".
 */
export interface Datum {
  label: string;
  value: number;
}
/**
 * This interface was referenced by `MotionSchema`'s JSON-Schema
 * via the `definition` "DocumentCardProps".
 */
export interface DocumentCardProps {
  accent: string | null;
  enter: "fade" | "pop" | "slide_up" | "slide_left" | "none";
  exit: "fade" | "slide_down" | "shrink" | "none";
  image_asset_id: string | null;
  /**
   * @maxItems 6
   */
  lines:
    | []
    | [string]
    | [string, string]
    | [string, string, string]
    | [string, string, string, string]
    | [string, string, string, string, string]
    | [string, string, string, string, string, string];
  subtitle: string | null;
  title: string;
}
/**
 * This interface was referenced by `MotionSchema`'s JSON-Schema
 * via the `definition` "GamifiedTimerProps".
 */
export interface GamifiedTimerProps {
  accent: string | null;
  enter: "fade" | "pop" | "slide_up" | "slide_left" | "none";
  exit: "fade" | "slide_down" | "shrink" | "none";
  label: string | null;
  position: "top" | "bottom" | "center" | "top_left" | "top_right" | "bottom_left" | "bottom_right";
  total_seconds: number;
  /**
   * Seconds left when the timer turns red and pulses
   */
  warn_at: number;
}
/**
 * This interface was referenced by `MotionSchema`'s JSON-Schema
 * via the `definition` "HighlightProps".
 */
export interface HighlightProps {
  accent: string | null;
  enter: "fade" | "pop" | "slide_up" | "slide_left" | "none";
  exit: "fade" | "slide_down" | "shrink" | "none";
  region: Region;
  shape: "box" | "underline" | "circle";
}
/**
 * A box in frame units (0..1), so it survives a change of output size.
 *
 * This interface was referenced by `MotionSchema`'s JSON-Schema
 * via the `definition` "Region".
 */
export interface Region {
  height: number;
  width: number;
  x: number;
  y: number;
}
/**
 * This interface was referenced by `MotionSchema`'s JSON-Schema
 * via the `definition` "LogoRevealProps".
 */
export interface LogoRevealProps {
  accent: string | null;
  enter: "fade" | "pop" | "slide_up" | "slide_left" | "none";
  exit: "fade" | "slide_down" | "shrink" | "none";
  image_asset_id: string | null;
  style: "fade" | "scale" | "glitch";
  tagline: string | null;
  text: string;
}
/**
 * This interface was referenced by `MotionSchema`'s JSON-Schema
 * via the `definition` "NotificationProps".
 */
export interface NotificationProps {
  accent: string | null;
  app: string;
  body: string;
  enter: "fade" | "pop" | "slide_up" | "slide_left" | "none";
  exit: "fade" | "slide_down" | "shrink" | "none";
  icon: "telegram" | "instagram" | "message" | "bell";
  title: string;
}
/**
 * This interface was referenced by `MotionSchema`'s JSON-Schema
 * via the `definition` "PhoneMockupProps".
 */
export interface PhoneMockupProps {
  accent: string | null;
  caption: string | null;
  enter: "fade" | "pop" | "slide_up" | "slide_left" | "none";
  exit: "fade" | "slide_down" | "shrink" | "none";
  image_asset_id: string | null;
  position: "left" | "center" | "right";
}
/**
 * This interface was referenced by `MotionSchema`'s JSON-Schema
 * via the `definition` "ProgressBarProps".
 */
export interface ProgressBarProps {
  accent: string | null;
  /**
   * @maxItems 10
   */
  chapters:
    | []
    | [Chapter]
    | [Chapter, Chapter]
    | [Chapter, Chapter, Chapter]
    | [Chapter, Chapter, Chapter, Chapter]
    | [Chapter, Chapter, Chapter, Chapter, Chapter]
    | [Chapter, Chapter, Chapter, Chapter, Chapter, Chapter]
    | [Chapter, Chapter, Chapter, Chapter, Chapter, Chapter, Chapter]
    | [Chapter, Chapter, Chapter, Chapter, Chapter, Chapter, Chapter, Chapter]
    | [Chapter, Chapter, Chapter, Chapter, Chapter, Chapter, Chapter, Chapter, Chapter]
    | [Chapter, Chapter, Chapter, Chapter, Chapter, Chapter, Chapter, Chapter, Chapter, Chapter];
  enter: "fade" | "pop" | "slide_up" | "slide_left" | "none";
  exit: "fade" | "slide_down" | "shrink" | "none";
  position: "top" | "bottom";
}
/**
 * This interface was referenced by `MotionSchema`'s JSON-Schema
 * via the `definition` "Chapter".
 */
export interface Chapter {
  /**
   * Seconds from the start of the item
   */
  at: number;
  title: string;
}
/**
 * This interface was referenced by `MotionSchema`'s JSON-Schema
 * via the `definition` "QuizCardProps".
 */
export interface QuizCardProps {
  accent: string | null;
  correct_index: number | null;
  enter: "fade" | "pop" | "slide_up" | "slide_left" | "none";
  exit: "fade" | "slide_down" | "shrink" | "none";
  /**
   * @minItems 2
   * @maxItems 4
   */
  options: [string, string] | [string, string, string] | [string, string, string, string];
  question: string;
  /**
   * Seconds after the card appears
   */
  reveal_at: number | null;
}
/**
 * This interface was referenced by `MotionSchema`'s JSON-Schema
 * via the `definition` "ScoreCounterProps".
 */
export interface ScoreCounterProps {
  accent: string | null;
  decimals: number;
  enter: "fade" | "pop" | "slide_up" | "slide_left" | "none";
  exit: "fade" | "slide_down" | "shrink" | "none";
  from_value: number;
  label: string | null;
  position: "top" | "bottom" | "center" | "top_left" | "top_right" | "bottom_left" | "bottom_right";
  prefix: string;
  suffix: string;
  to_value: number;
}
/**
 * This interface was referenced by `MotionSchema`'s JSON-Schema
 * via the `definition` "TitleCardProps".
 */
export interface TitleCardProps {
  accent: string | null;
  enter: "fade" | "pop" | "slide_up" | "slide_left" | "none";
  exit: "fade" | "slide_down" | "shrink" | "none";
  subtitle: string | null;
  title: string;
  variant: "full" | "lower_third";
}
/**
 * This interface was referenced by `MotionSchema`'s JSON-Schema
 * via the `definition` "OverlayProps".
 */
export interface OverlayProps {
  assets: {
    [k: string]: string;
  };
  captions: CaptionsOverlay | null;
  duration_in_frames: number;
  fps: number;
  height: number;
  items: OverlayItem[];
  safe_zone: SafeZone;
  schema_version: "overlay/1";
  theme: Theme;
  width: number;
}
/**
 * This interface was referenced by `MotionSchema`'s JSON-Schema
 * via the `definition` "CaptionsOverlay".
 */
export interface CaptionsOverlay {
  lines: CaptionLine[];
  position: "bottom" | "center" | "top";
  style: "dynamic" | "karaoke" | "minimal" | "bold";
}
/**
 * This interface was referenced by `MotionSchema`'s JSON-Schema
 * via the `definition` "CaptionLine".
 */
export interface CaptionLine {
  end: number;
  start: number;
  words: OverlayWord[];
}
/**
 * This interface was referenced by `MotionSchema`'s JSON-Schema
 * via the `definition` "OverlayWord".
 */
export interface OverlayWord {
  end: number;
  start: number;
  text: string;
}
/**
 * This interface was referenced by `MotionSchema`'s JSON-Schema
 * via the `definition` "OverlayItem".
 */
export interface OverlayItem {
  component: string;
  duration_frames: number;
  from_frame: number;
  id: string;
  layer: number;
  props: {
    [k: string]: unknown;
  };
}
/**
 * Insets (fractions of the frame) that platform UI covers: on 9:16 the
 * caption must clear the like/comment column and the description.
 *
 * This interface was referenced by `MotionSchema`'s JSON-Schema
 * via the `definition` "SafeZone".
 */
export interface SafeZone {
  bottom: number;
  left: number;
  right: number;
  top: number;
}
/**
 * This interface was referenced by `MotionSchema`'s JSON-Schema
 * via the `definition` "Theme".
 */
export interface Theme {
  accent: string;
  font: "Inter" | "Montserrat";
  highlight: string;
  primary: string;
  text: string;
}
