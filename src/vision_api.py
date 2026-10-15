"""OpenCV-backed, single-frame pedestrian analysis for Campus Twin.

The endpoint intentionally processes an uploaded still image, not a live CCTV feed.
By default it uses OpenCV's built-in HOG pedestrian detector. Set VISION_MODEL_PATH
to a compatible YOLOv8 COCO ONNX export to run inference through OpenCV DNN.
"""
from __future__ import annotations

import base64
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from src.auth import require_api_key

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/vision", tags=["vision"])

MAX_UPLOAD_BYTES = 8 * 1024 * 1024
MAX_IMAGE_PIXELS = 25_000_000
MAX_FRAME_SIDE = 1280
MAX_DETECTIONS = 50
YOLO_INPUT_SIZE = 640
ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}


def _confidence_threshold() -> float:
    try:
        threshold = float(os.getenv("VISION_CONFIDENCE_THRESHOLD", "0.25"))
    except ValueError:
        threshold = 0.25
    return min(0.95, max(0.05, threshold))


def _detect_with_hog(frame: np.ndarray) -> list[dict[str, Any]]:
    """Run OpenCV's built-in pedestrian HOG detector; no external weights required."""
    detector = cv2.HOGDescriptor()
    detector.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())
    boxes, _weights = detector.detectMultiScale(
        frame,
        hitThreshold=0.0,
        winStride=(8, 8),
        padding=(8, 8),
        scale=1.05,
    )
    detections: list[dict[str, Any]] = []
    for x, y, width, height in list(boxes)[:MAX_DETECTIONS]:
        detections.append(
            {
                "x": max(0, int(x)),
                "y": max(0, int(y)),
                "width": max(1, int(width)),
                "height": max(1, int(height)),
                "label": "person",
            }
        )
    return detections


def _detect_with_yolo_onnx(
    frame: np.ndarray, model_path: Path
) -> list[dict[str, Any]]:
    """Run a YOLOv8 (84 x N) or YOLOv5 (85 x N) COCO ONNX model using OpenCV DNN."""
    if not model_path.is_file():
        raise FileNotFoundError(f"Configured ONNX model was not found: {model_path}")

    network = cv2.dnn.readNetFromONNX(str(model_path))
    height, width = frame.shape[:2]
    scale = min(YOLO_INPUT_SIZE / width, YOLO_INPUT_SIZE / height)
    resized_width = max(1, round(width * scale))
    resized_height = max(1, round(height * scale))
    resized = cv2.resize(frame, (resized_width, resized_height), interpolation=cv2.INTER_LINEAR)

    pad_x = (YOLO_INPUT_SIZE - resized_width) // 2
    pad_y = (YOLO_INPUT_SIZE - resized_height) // 2
    canvas = np.full((YOLO_INPUT_SIZE, YOLO_INPUT_SIZE, 3), 114, dtype=np.uint8)
    canvas[pad_y : pad_y + resized_height, pad_x : pad_x + resized_width] = resized

    blob = cv2.dnn.blobFromImage(
        canvas, scalefactor=1.0 / 255.0, size=(YOLO_INPUT_SIZE, YOLO_INPUT_SIZE),
        swapRB=True, crop=False
    )
    network.setInput(blob)
    prediction = np.asarray(network.forward())
    if prediction.ndim == 3:
        prediction = prediction[0]
    if prediction.ndim != 2:
        raise ValueError("Unexpected ONNX output rank.")

    # Common exports return (84, N)/(85, N); others return (N, 84)/(N, 85).
    if prediction.shape[0] in (84, 85) and prediction.shape[1] > prediction.shape[0]:
        prediction = prediction.T
    feature_count = prediction.shape[1]
    if feature_count not in (84, 85):
        raise ValueError(
            f"Unsupported ONNX output shape {prediction.shape}; expected 84 or 85 features."
        )

    threshold = _confidence_threshold()
    boxes_for_nms: list[list[int]] = []
    scores: list[float] = []
    mapped_boxes: list[dict[str, Any]] = []

    for row in prediction:
        if feature_count == 85:
            # YOLOv5 layout: [cx, cy, w, h, objectness, 80 class scores].
            score = float(row[4]) * float(row[5])
        else:
            # YOLOv8 layout: [cx, cy, w, h, 80 class scores]; class 0 is person.
            score = float(row[4])
        if not np.isfinite(score) or score < threshold:
            continue

        center_x, center_y, box_width, box_height = (float(value) for value in row[:4])
        x1 = int(round((center_x - box_width / 2 - pad_x) / scale))
        y1 = int(round((center_y - box_height / 2 - pad_y) / scale))
        x2 = int(round((center_x + box_width / 2 - pad_x) / scale))
        y2 = int(round((center_y + box_height / 2 - pad_y) / scale))

        x1 = max(0, min(width - 1, x1))
        y1 = max(0, min(height - 1, y1))
        x2 = max(0, min(width, x2))
        y2 = max(0, min(height, y2))
        box_width_out, box_height_out = x2 - x1, y2 - y1
        if box_width_out < 2 or box_height_out < 2:
            continue

        boxes_for_nms.append([x1, y1, box_width_out, box_height_out])
        scores.append(score)
        mapped_boxes.append(
            {
                "x": x1,
                "y": y1,
                "width": box_width_out,
                "height": box_height_out,
                "label": "person",
            }
        )

    if not boxes_for_nms:
        return []

    kept = cv2.dnn.NMSBoxes(
        boxes_for_nms, scores, _confidence_threshold(), 0.45
    )
    if kept is None or len(kept) == 0:
        return []
    indices = [int(index) for index in np.asarray(kept).reshape(-1)]
    indices.sort(key=lambda index: scores[index], reverse=True)
    return [mapped_boxes[index] for index in indices[:MAX_DETECTIONS]]


def detect_people(frame: np.ndarray) -> tuple[list[dict[str, Any]], str]:
    """Select configured OpenCV DNN model or explicit no-weights HOG baseline."""
    configured_model = os.getenv("VISION_MODEL_PATH", "").strip()
    if configured_model:
        return _detect_with_yolo_onnx(frame, Path(configured_model)), "OpenCV DNN · YOLO ONNX"
    return _detect_with_hog(frame), "OpenCV HOG pedestrian detector"


def _annotate(frame: np.ndarray, detections: list[dict[str, Any]]) -> str:
    preview = frame.copy()
    for detection in detections:
        x, y = detection["x"], detection["y"]
        x2 = x + detection["width"]
        y2 = y + detection["height"]
        cv2.rectangle(preview, (x, y), (x2, y2), (39, 220, 160), 2)
        cv2.putText(
            preview, "person", (x, max(18, y - 7)),
            cv2.FONT_HERSHEY_SIMPLEX, 0.55, (39, 220, 160), 2, cv2.LINE_AA
        )

    success, encoded = cv2.imencode(".jpg", preview, [int(cv2.IMWRITE_JPEG_QUALITY), 84])
    if not success:
        raise ValueError("Could not encode annotated frame.")
    payload = base64.b64encode(encoded.tobytes()).decode("ascii")
    return f"data:image/jpeg;base64,{payload}"


@router.post(
    "/pedestrians",
    dependencies=[Depends(require_api_key)],
    summary="Count visible pedestrians in an uploaded campus frame",
)
async def analyze_pedestrian_frame(
    file: UploadFile = File(...),
    zone_id: str = Form(..., min_length=1, max_length=80),
    camera_label: str = Form(default="Uploaded frame", min_length=1, max_length=80),
) -> dict[str, Any]:
    """Analyze one uploaded image and return detections with transparent provenance."""
    content_type = (file.content_type or "").split(";", maxsplit=1)[0].strip().lower()
    if content_type and content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(status_code=415, detail="Unggah gambar JPEG, PNG, atau WebP.")

    try:
        payload = await file.read(MAX_UPLOAD_BYTES + 1)
    finally:
        await file.close()

    if not payload:
        raise HTTPException(status_code=400, detail="File gambar kosong.")
    if len(payload) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Ukuran gambar melebihi batas 8 MiB.")

    encoded = np.frombuffer(payload, dtype=np.uint8)
    frame = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
    if frame is None:
        raise HTTPException(status_code=400, detail="File tidak dapat didekode sebagai gambar.")
    original_height, original_width = frame.shape[:2]
    if original_width * original_height > MAX_IMAGE_PIXELS:
        raise HTTPException(status_code=413, detail="Resolusi gambar terlalu besar.")

    resize_scale = min(1.0, MAX_FRAME_SIDE / max(original_width, original_height))
    if resize_scale < 1.0:
        frame = cv2.resize(
            frame,
            (max(1, round(original_width * resize_scale)), max(1, round(original_height * resize_scale))),
            interpolation=cv2.INTER_AREA,
        )

    safe_zone_id = zone_id.strip()
    safe_camera_label = camera_label.strip()
    if not safe_zone_id or not safe_camera_label:
        raise HTTPException(status_code=422, detail="Zona dan label kamera wajib diisi.")

    try:
        detections, detector_name = detect_people(frame)
        annotated_image = _annotate(frame, detections)
    except FileNotFoundError as exc:
        logger.warning("Configured vision model is unavailable.")
        raise HTTPException(
            status_code=503,
            detail="Model ONNX belum ditemukan. Periksa VISION_MODEL_PATH atau kosongkan untuk memakai HOG.",
        ) from exc
    except (cv2.error, ValueError, OSError) as exc:
        logger.exception("OpenCV frame analysis failed.")
        raise HTTPException(
            status_code=503,
            detail="Pipeline OpenCV gagal memproses gambar. Periksa format dan konfigurasi model.",
        ) from exc

    height, width = frame.shape[:2]
    return {
        "status": "completed",
        "source_type": "uploaded_image",
        "data_label": "OBSERVED_FROM_UPLOADED_IMAGE",
        "zone_id": safe_zone_id,
        "camera_label": safe_camera_label,
        "detector": detector_name,
        "processed_at": datetime.now(timezone.utc).isoformat(),
        "frame_width": width,
        "frame_height": height,
        "people_count": len(detections),
        "detections": detections,
        "annotated_image": annotated_image,
        "limitations": [
            "Analisis hanya berdasarkan satu gambar yang diunggah, bukan stream CCTV live.",
            "Jumlah menghitung orang yang terlihat dan terdeteksi pada frame ini; bukan identitas unik atau occupancy terkalibrasi.",
            "Hasil frame ini tidak disimpan sebagai histori dan tidak otomatis mengubah status perangkat/gedung.",
        ],
    }
