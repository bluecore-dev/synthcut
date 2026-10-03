"""Motion-graphics component registry (spec §19).

Agents may only place components that exist here — they do not invent new
ones. Every entry has a typed props model (validated by ``validate_plan`` as
``E_COMPONENT_PROPS``) and exactly one Remotion implementation in
``apps/remotion/src/widgets/``; the TypeScript prop types are generated from
these models (``make motion-types``), so the two cannot drift.

Text limits are layout limits: a title that fits the safe zone at 1080 px
wide in two lines, not a database column size.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator

Color = Annotated[str, Field(pattern=r"^#[0-9A-Fa-f]{6}$")]
Unit = Annotated[float, Field(ge=0, le=1)]
Enter = Literal["fade", "pop", "slide_up", "slide_left", "none"]
Exit = Literal["fade", "slide_down", "shrink", "none"]


class Props(BaseModel):
    """Common to every component: how it appears and leaves, and an optional
    accent colour (the project theme is used otherwise)."""

    # Serialised props always carry every field (defaults filled by build_overlay),
    # so the generated TypeScript types mark them present.
    model_config = ConfigDict(extra="forbid", json_schema_serialization_defaults_required=True)

    enter: Enter = "pop"
    exit: Exit = "fade"
    accent: Color | None = None


Corner = Literal["top", "bottom", "center", "top_left", "top_right", "bottom_left", "bottom_right"]


class GamifiedTimerProps(Props):
    # The spec's own example writes {"totalTime": 30}; both spellings are accepted.
    total_seconds: int = Field(ge=1, le=3600, validation_alias=AliasChoices("total_seconds", "totalTime"))
    label: str | None = Field(None, max_length=40)
    warn_at: int = Field(5, ge=0, le=60, description="Seconds left when the timer turns red and pulses")
    position: Corner = "top_right"


class QuizCardProps(Props):
    question: str = Field(min_length=1, max_length=120)
    options: list[Annotated[str, Field(min_length=1, max_length=60)]] = Field(min_length=2, max_length=4)
    correct_index: int | None = Field(None, ge=0, le=3)
    reveal_at: float | None = Field(None, ge=0, description="Seconds after the card appears")

    @model_validator(mode="after")
    def _answer_exists(self) -> QuizCardProps:
        if self.correct_index is not None and self.correct_index >= len(self.options):
            raise ValueError("correct_index points past the options")
        return self


class AbacusWidgetProps(Props):
    value: int = Field(ge=0, le=999_999_999)
    rods: int = Field(5, ge=3, le=9)
    from_value: int | None = Field(None, ge=0, le=999_999_999)
    position: Corner = "center"


class DocumentCardProps(Props):
    title: str = Field(min_length=1, max_length=80)
    subtitle: str | None = Field(None, max_length=120)
    lines: list[Annotated[str, Field(max_length=80)]] = Field(default_factory=list, max_length=6)
    image_asset_id: UUID | None = None


class ScoreCounterProps(Props):
    to_value: float
    from_value: float = 0
    decimals: int = Field(0, ge=0, le=2)
    prefix: str = Field("", max_length=10)
    suffix: str = Field("", max_length=10)
    label: str | None = Field(None, max_length=40)
    position: Corner = "center"


class AnimatedSubtitleProps(Props):
    text: str = Field(min_length=1, max_length=120)
    highlight: list[Annotated[str, Field(max_length=30)]] = Field(default_factory=list, max_length=6)
    position: Literal["top", "center", "bottom"] = "bottom"


class TitleCardProps(Props):
    title: str = Field(min_length=1, max_length=60)
    subtitle: str | None = Field(None, max_length=100)
    variant: Literal["full", "lower_third"] = "lower_third"


class CTAProps(Props):
    text: str = Field(min_length=1, max_length=40)
    action: Literal["subscribe", "follow", "like", "comment", "link"] = "subscribe"
    handle: str | None = Field(None, max_length=40)
    position: Literal["bottom", "center"] = "bottom"


class LogoRevealProps(Props):
    text: str = Field(min_length=1, max_length=30)
    tagline: str | None = Field(None, max_length=60)
    image_asset_id: UUID | None = None
    style: Literal["fade", "scale", "glitch"] = "scale"


class Chapter(BaseModel):
    model_config = ConfigDict(extra="forbid", json_schema_serialization_defaults_required=True)
    title: str = Field(min_length=1, max_length=30)
    at: float = Field(ge=0, description="Seconds from the start of the item")


class ProgressBarProps(Props):
    chapters: list[Chapter] = Field(default_factory=list, max_length=10)
    position: Literal["top", "bottom"] = "top"
    enter: Enter = "fade"


class Datum(BaseModel):
    model_config = ConfigDict(extra="forbid", json_schema_serialization_defaults_required=True)
    label: str = Field(min_length=1, max_length=20)
    value: float


class ChartProps(Props):
    kind: Literal["bar", "line", "pie"] = "bar"
    title: str | None = Field(None, max_length=60)
    series: list[Datum] = Field(min_length=1, max_length=8)
    unit: str = Field("", max_length=10)


class PhoneMockupProps(Props):
    image_asset_id: UUID | None = None
    caption: str | None = Field(None, max_length=60)
    position: Literal["left", "center", "right"] = "right"


class NotificationProps(Props):
    app: str = Field("Telegram", min_length=1, max_length=24)
    title: str = Field(min_length=1, max_length=40)
    body: str = Field("", max_length=90)
    icon: Literal["telegram", "instagram", "message", "bell"] = "telegram"
    enter: Enter = "slide_left"


class Region(BaseModel):
    """A box in frame units (0..1), so it survives a change of output size."""

    model_config = ConfigDict(extra="forbid", json_schema_serialization_defaults_required=True)
    x: Unit
    y: Unit
    width: Unit
    height: Unit

    @model_validator(mode="after")
    def _inside(self) -> Region:
        if self.x + self.width > 1.0001 or self.y + self.height > 1.0001:
            raise ValueError("region leaves the frame")
        return self


class HighlightProps(Props):
    region: Region
    shape: Literal["box", "underline", "circle"] = "box"


class Point(BaseModel):
    model_config = ConfigDict(extra="forbid", json_schema_serialization_defaults_required=True)
    x: Unit
    y: Unit


class CalloutProps(Props):
    target: Point
    text: str = Field(min_length=1, max_length=40)
    side: Literal["left", "right", "top", "bottom"] = "right"


@dataclass(frozen=True, slots=True)
class ComponentSpec:
    name: str
    description: str
    props_model: type[Props] | None = None
    phase: int = 7
    # Library sound played when the component enters (assets/sfx); the plan
    # may override it with its own sfx track.
    sfx: str | None = None
    min_duration: float = 0.5


GRAPHICS_REGISTRY: dict[str, ComponentSpec] = {
    spec.name: spec
    for spec in (
        ComponentSpec(
            "GamifiedTimer",
            "Countdown timer with game-like styling",
            GamifiedTimerProps,
            sfx="sfx/tick",
            min_duration=1.0,
        ),
        ComponentSpec(
            "QuizCard",
            "Question with answer options; reveals the right one",
            QuizCardProps,
            sfx="sfx/pop",
            min_duration=2.0,
        ),
        ComponentSpec(
            "AbacusWidget",
            "Animated abacus / mental arithmetic visual",
            AbacusWidgetProps,
            sfx="sfx/tick",
            min_duration=1.5,
        ),
        ComponentSpec(
            "DocumentCard",
            "Document or screenshot presented as a card",
            DocumentCardProps,
            sfx="sfx/whoosh",
            min_duration=1.5,
        ),
        ComponentSpec(
            "ScoreCounter", "Animated number counter", ScoreCounterProps, sfx="sfx/ding", min_duration=1.0
        ),
        ComponentSpec(
            "AnimatedSubtitle", "Word-by-word animated subtitle line", AnimatedSubtitleProps, min_duration=0.5
        ),
        ComponentSpec(
            "TitleCard", "Full-frame or lower-third title", TitleCardProps, sfx="sfx/whoosh", min_duration=1.0
        ),
        ComponentSpec(
            "CTA", "Call to action (follow / subscribe / link)", CTAProps, sfx="sfx/pop", min_duration=1.5
        ),
        ComponentSpec(
            "LogoReveal", "Brand logo animation", LogoRevealProps, sfx="sfx/whoosh", min_duration=1.5
        ),
        ComponentSpec("ProgressBar", "Video progress / chapter bar", ProgressBarProps, min_duration=1.0),
        ComponentSpec(
            "Chart", "Animated bar / line / pie chart", ChartProps, sfx="sfx/whoosh", min_duration=2.0
        ),
        ComponentSpec(
            "PhoneMockup",
            "Content shown inside a phone frame",
            PhoneMockupProps,
            sfx="sfx/whoosh",
            min_duration=1.5,
        ),
        ComponentSpec(
            "Notification",
            "Phone-style notification pop-up",
            NotificationProps,
            sfx="sfx/notify",
            min_duration=1.5,
        ),
        ComponentSpec("Highlight", "Marker highlight over a region", HighlightProps, min_duration=0.5),
        ComponentSpec(
            "Callout", "Arrow / label pointing at something", CalloutProps, sfx="sfx/pop", min_duration=1.0
        ),
    )
}
