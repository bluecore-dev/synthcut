"""Motion-graphics component registry (spec §19).

Agents may only place components that exist here — they do not invent new
ones. Each entry is implemented once as a Remotion component (Phase 7); until
its ``props_model`` is defined, props are accepted as-is but the component is
still name-checked.
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel


@dataclass(frozen=True, slots=True)
class ComponentSpec:
    name: str
    description: str
    props_model: type[BaseModel] | None = None
    phase: int = 7


GRAPHICS_REGISTRY: dict[str, ComponentSpec] = {
    spec.name: spec
    for spec in (
        ComponentSpec("GamifiedTimer", "Countdown timer with game-like styling"),
        ComponentSpec("QuizCard", "Question with answer options"),
        ComponentSpec("AbacusWidget", "Animated abacus / mental arithmetic visual"),
        ComponentSpec("DocumentCard", "Document or screenshot presented as a card"),
        ComponentSpec("ScoreCounter", "Animated number counter"),
        ComponentSpec("AnimatedSubtitle", "Word-by-word animated subtitle line"),
        ComponentSpec("TitleCard", "Full-frame or lower-third title"),
        ComponentSpec("CTA", "Call to action (follow / subscribe / link)"),
        ComponentSpec("LogoReveal", "Brand logo animation"),
        ComponentSpec("ProgressBar", "Video progress / chapter bar"),
        ComponentSpec("Chart", "Animated bar / line / pie chart"),
        ComponentSpec("PhoneMockup", "Content shown inside a phone frame"),
        ComponentSpec("Notification", "Phone-style notification pop-up"),
        ComponentSpec("Highlight", "Marker highlight over a region"),
        ComponentSpec("Callout", "Arrow / label pointing at something"),
    )
}
