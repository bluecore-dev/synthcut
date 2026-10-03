"""The normalized media description is a shared contract (stored in the
database, read by the API, the Mini App and the agents), so it lives in
``synthcut_schemas.media``; re-exported here for the engine's own use."""

from synthcut_schemas.media import (  # noqa: F401
    AudioStream,
    ColorInfo,
    ColorProfileId,
    Loudness,
    MediaInfo,
    MediaKind,
    VideoStream,
)
