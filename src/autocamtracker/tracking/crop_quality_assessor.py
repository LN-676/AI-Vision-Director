"""Crop validation and JPEG encoding for feature enrollment."""

from __future__ import annotations

from autocamtracker.tracking.feature_models import CropQuality


class CropQualityAssessor:
    def assess(self, frame, bbox: tuple[float, float, float, float]) -> CropQuality:
        import cv2

        crop = self.crop(frame, bbox)
        if crop is None:
            return CropQuality(False, 0.0, "bbox is outside the frame", 0, 0, 0.0, 0.0)
        height, width = crop.shape[:2]
        area = width * height
        if width < 32 or height < 32 or area < 1600:
            return CropQuality(False, 0.0, "crop is too small", width, height, 0.0, 0.0)
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        brightness = float(gray.mean())
        if brightness < 20.0 or brightness > 240.0:
            return CropQuality(False, 0.0, "crop brightness is outside usable range", width, height, sharpness, brightness)
        if sharpness < 5.0:
            return CropQuality(False, 0.0, "crop is too blurry", width, height, sharpness, brightness)
        area_score = min(1.0, area / 12000.0)
        sharpness_score = min(1.0, sharpness / 120.0)
        brightness_score = max(0.0, 1.0 - abs(brightness - 128.0) / 128.0)
        score = 0.45 * area_score + 0.40 * sharpness_score + 0.15 * brightness_score
        return CropQuality(True, float(score), "ok", width, height, sharpness, brightness)

    @staticmethod
    def feature_bbox(frame, bbox: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
        frame_h, frame_w = frame.shape[:2]
        x1, y1, x2, y2 = bbox
        center_x, center_y = (x1 + x2) / 2.0, (y1 + y2) / 2.0
        target_w = min(float(frame_w), max(64.0, (x2 - x1) * 1.25))
        target_h = min(float(frame_h), max(64.0, (y2 - y1) * 1.25))
        left = max(0.0, min(float(frame_w) - target_w, center_x - target_w / 2.0))
        top = max(0.0, min(float(frame_h) - target_h, center_y - target_h / 2.0))
        return (left, top, left + target_w, top + target_h)

    def crop(self, frame, bbox: tuple[float, float, float, float]):
        if frame is None:
            return None
        frame_h, frame_w = frame.shape[:2]
        x1, y1, x2, y2 = self.feature_bbox(frame, bbox)
        left, top = max(0, min(frame_w - 1, round(x1))), max(0, min(frame_h - 1, round(y1)))
        right, bottom = max(left + 1, min(frame_w, round(x2))), max(top + 1, min(frame_h, round(y2)))
        return None if right <= left or bottom <= top else frame[top:bottom, left:right]

    def encode_jpeg(self, frame, bbox: tuple[float, float, float, float]) -> bytes | None:
        import cv2

        crop = self.crop(frame, bbox)
        if crop is None:
            return None
        ok, encoded = cv2.imencode(".jpg", crop, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
        return bytes(encoded) if ok else None
