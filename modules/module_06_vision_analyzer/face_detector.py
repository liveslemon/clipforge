"""Face detection with OpenCV's YuNet (CNN detector shipped in OpenCV ≥ 4.8), sampled across a video.

Benchmarked on real uploads (60 sampled frames each): YuNet found faces in 75% / 45% of frames vs 5% / 10% for
MediaPipe BlazeFace short-range and ~15% for the old Haar cascade, including small background faces.
"""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Tuple

from ..config import MODELS_DIR
from .models import BoundingBox

YUNET_FILE = "face_detection_yunet_2023mar.onnx"
YUNET_URL = "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx"


class FaceDetectorError(Exception):
    pass


def ensure_yunet_model(models_dir: Path = MODELS_DIR) -> Path:
    path = models_dir / YUNET_FILE
    if not path.exists():
        import urllib.request
        models_dir.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(YUNET_URL, path)
    return path


class YuNetFaceDetector:
    def __init__(self, model_path: Optional[Path] = None, score_threshold: float = 0.6, nms_threshold: float = 0.3):
        try:
            import cv2
        except ImportError as e:
            raise FaceDetectorError("OpenCV is not installed (pip install opencv-python).") from e
        if not hasattr(cv2, "FaceDetectorYN"):
            raise FaceDetectorError("This OpenCV build has no FaceDetectorYN (need OpenCV ≥ 4.8).")
        self.cv2 = cv2
        self.model_path = Path(model_path) if model_path else ensure_yunet_model()
        self.detector = cv2.FaceDetectorYN.create(str(self.model_path), "", (320, 320), score_threshold, nms_threshold, 5000)
        self._size: Tuple[int, int] = (0, 0)

    def detect(self, image_bgr) -> List[Tuple[BoundingBox, float]]:
        """All faces in a BGR frame as (box, confidence), largest first."""
        h, w = image_bgr.shape[:2]
        if (w, h) != self._size:
            self.detector.setInputSize((w, h))
            self._size = (w, h)
        _, faces = self.detector.detect(image_bgr)
        out = []
        for f in faces if faces is not None else []:
            x, y, fw, fh = (int(round(v)) for v in f[:4])
            x, y = max(0, x), max(0, y)
            fw, fh = min(w - x, fw), min(h - y, fh)
            if fw > 4 and fh > 4:
                out.append((BoundingBox(x=x, y=y, width=fw, height=fh), float(f[-1])))
        return sorted(out, key=lambda d: d[0].width * d[0].height, reverse=True)

    def track_video(self, video_path: str | Path, sample_fps: float = 4.0, max_samples: int = 2400,
                    out_size: Optional[Tuple[int, int]] = None) -> List[Tuple[float, BoundingBox, float]]:
        """Samples frames and returns (timestamp_s, main face box, confidence) for frames with a face.

        out_size: map boxes to this (width, height) — e.g. the source resolution when scanning a smaller proxy.
        The main face is the largest one (the streamer's cam / the person closest to camera).
        """
        cap = self.cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            raise FaceDetectorError(f"Could not open video: {video_path}")
        fps = cap.get(self.cv2.CAP_PROP_FPS) or 30.0
        total = int(cap.get(self.cv2.CAP_PROP_FRAME_COUNT)) or 0
        step = max(1, int(round(fps / sample_fps)))
        if total and total / step > max_samples:
            step = max(1, total // max_samples)
        results = []
        idx = 0
        while True:
            ok = cap.grab()
            if not ok:
                break
            if idx % step == 0:
                ok, frame = cap.retrieve()
                if ok:
                    faces = self.detect(frame)
                    if faces:
                        box, conf = faces[0]
                        if out_size:
                            sx, sy = out_size[0] / frame.shape[1], out_size[1] / frame.shape[0]
                            box = BoundingBox(x=int(box.x * sx), y=int(box.y * sy),
                                              width=int(box.width * sx), height=int(box.height * sy))
                        results.append((round(idx / fps, 3), box, conf))
            idx += 1
        cap.release()
        return results
