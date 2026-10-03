from __future__ import annotations


class MediaError(RuntimeError):
    """A media operation failed. ``permanent`` means retrying cannot help
    (corrupt or unsupported file); otherwise it may be transient (I/O)."""

    def __init__(self, message: str, *, permanent: bool) -> None:
        super().__init__(message)
        self.permanent = permanent
