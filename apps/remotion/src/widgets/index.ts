// The Remotion side of the registry: exactly one component per entry of
// packages/timeline/synthcut_timeline/registry.py (a test checks both lists).
import type { ComponentType } from "react";
import type { ComponentProps } from "../generated/types";
import { AbacusWidget } from "./AbacusWidget";
import { AnimatedSubtitle } from "./AnimatedSubtitle";
import { Callout } from "./Callout";
import { Chart } from "./Chart";
import type { WidgetProps } from "./common";
import { CTA } from "./CTA";
import { DocumentCard } from "./DocumentCard";
import { GamifiedTimer } from "./GamifiedTimer";
import { Highlight } from "./Highlight";
import { LogoReveal } from "./LogoReveal";
import { Notification } from "./Notification";
import { PhoneMockup } from "./PhoneMockup";
import { ProgressBar } from "./ProgressBar";
import { QuizCard } from "./QuizCard";
import { ScoreCounter } from "./ScoreCounter";
import { TitleCard } from "./TitleCard";

export type ComponentName = keyof ComponentProps;

export const WIDGETS: { [K in ComponentName]: ComponentType<WidgetProps<ComponentProps[K]>> } = {
  AbacusWidget,
  AnimatedSubtitle,
  CTA,
  Callout,
  Chart,
  DocumentCard,
  GamifiedTimer,
  Highlight,
  LogoReveal,
  Notification,
  PhoneMockup,
  ProgressBar,
  QuizCard,
  ScoreCounter,
  TitleCard,
};
