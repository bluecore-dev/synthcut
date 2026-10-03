"""Faces with YuNet (OpenCV's CPU face detector, MIT licence, 230 KB — shipped
in the package, no download). Faces give the shot type and where the person
stands; everything semantic is the vision agent's job."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
from synthcut_schemas.analysis import Face

MODEL = Path(__file__).parent / "models" / "face_detection_yunet_2023mar.onnx"

try:  # OpenCV's DNN prints backend notices on stderr, which end up in job logs
    cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_ERROR)
except AttributeError:  # pragma: no cover - builds without the logging module
    pass


class FaceDetector:
    def __init__(self, *, min_score: float = 0.75) -> None:
        self._det = cv2.FaceDetectorYN.create(str(MODEL), "", (320, 320), min_score, 0.3, 50)

    def detect(self, image: np.ndarray) -> list[Face]:
        h, w = image.shape[:2]
        self._det.setInputSize((w, h))
        _, found = self._det.detect(image)
        faces: list[Face] = []
        for row in found if found is not None else []:
            x, y, fw, fh = (float(v) for v in row[:4])
            faces.append(
                Face(
                    x=round(min(1.0, max(0.0, (x + fw / 2) / w)), 3),
                    y=round(min(1.0, max(0.0, (y + fh / 2) / h)), 3),
                    height=round(min(1.0, fh / h), 3),
                    score=round(float(row[-1]), 3),
                )
            )
        return sorted(faces, key=lambda f: f.height, reverse=True)


def shot_type(faces: list[Face]) -> str:
    """From the largest face: a head filling a third of the frame is a close-up."""
    if not faces:
        return "unknown"
    top = faces[0].height
    if top >= 0.30:
        return "close_up"
    if top >= 0.12:
        return "medium"
    return "wide"


def position(faces: list[Face]) -> str | None:
    if not faces:
        return None
    x = faces[0].x
    return "left" if x < 0.38 else "right" if x > 0.62 else "center"
