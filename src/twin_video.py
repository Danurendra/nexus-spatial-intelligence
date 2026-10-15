"""Video-to-spatial-state pipeline and SQLite evidence store for Vision Twin."""
from __future__ import annotations

import hashlib
from contextlib import closing
import json
import logging
import math
import os
import re
import sqlite3
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from src.vision_api import make_person_detector


logger = logging.getLogger(__name__)

MAX_VIDEO_SECONDS = 300
MAX_SAMPLES = 60
MAX_FRAME_SIDE = 1280
MAX_FRAME_PIXELS = 25_000_000
MAX_ZONES = 4
MIN_ZONES = 1
DEFAULT_ZONES = [
    {
        "zone_id": "corridor-a",
        "name": "Koridor A",
        "polygon_normalized": [[0.03, 0.08], [0.49, 0.08], [0.49, 0.97], [0.03, 0.97]],
        "occupancy_threshold": 3,
    },
    {
        "zone_id": "corridor-b",
        "name": "Koridor B",
        "polygon_normalized": [[0.51, 0.08], [0.97, 0.08], [0.97, 0.97], [0.51, 0.97]],
        "occupancy_threshold": 3,
    },
]
VALID_ZONE_ID = re.compile(r"^[A-Za-z0-9_-]{1,80}$")


class VisionPipelineError(RuntimeError):
    def __init__(self, message: str, status_code: int = 422, code: str = "VISION_PIPELINE_ERROR"):
        super().__init__(message)
        self.status_code = status_code
        self.code = code


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def opencv_version() -> str:
    return str(cv2.__version__)


def ensure_opencv_version() -> str:
    version = opencv_version()
    if os.getenv("VISION_REQUIRE_OPENCV5", "true").strip().lower() not in {"0", "false", "no", "off"}:
        major_match = re.match(r"^(\d+)", version)
        if not major_match or int(major_match.group(1)) != 5:
            raise VisionPipelineError(
                f"Video pipeline requires OpenCV 5.x; the current runtime reports {version}.",
                status_code=503,
                code="OPENCV_VERSION_MISMATCH",
            )
    return version


def parse_zones(raw: str | None) -> list[dict[str, Any]]:
    try:
        zones = DEFAULT_ZONES if not raw else json.loads(raw)
    except json.JSONDecodeError as exc:
        raise VisionPipelineError("Konfigurasi zona bukan JSON yang valid.", 422, "INVALID_ZONE_CONFIG") from exc

    if not isinstance(zones, list) or not MIN_ZONES <= len(zones) <= MAX_ZONES:
        raise VisionPipelineError("Konfigurasi harus berisi 1–4 zona.", 422, "INVALID_ZONE_CONFIG")

    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in zones:
        if not isinstance(item, dict):
            raise VisionPipelineError("Setiap zona harus berupa objek JSON.", 422, "INVALID_ZONE_CONFIG")
        zone_id = str(item.get("zone_id", "")).strip()
        name = str(item.get("name", zone_id)).strip()
        polygon = item.get("polygon_normalized")
        threshold = item.get("occupancy_threshold")
        if not VALID_ZONE_ID.fullmatch(zone_id) or zone_id in seen:
            raise VisionPipelineError("zone_id harus unik dan hanya berisi huruf, angka, _ atau -.", 422, "INVALID_ZONE_CONFIG")
        if not name or len(name) > 100:
            raise VisionPipelineError("Nama zona harus berisi 1–100 karakter.", 422, "INVALID_ZONE_CONFIG")
        if not isinstance(polygon, list) or not 3 <= len(polygon) <= 20:
            raise VisionPipelineError("Polygon setiap zona harus memiliki 3–20 titik.", 422, "INVALID_ZONE_CONFIG")
        points: list[list[float]] = []
        for point in polygon:
            if not isinstance(point, (list, tuple)) or len(point) != 2:
                raise VisionPipelineError("Setiap titik polygon harus berbentuk [x, y].", 422, "INVALID_ZONE_CONFIG")
            try:
                x, y = float(point[0]), float(point[1])
            except (TypeError, ValueError) as exc:
                raise VisionPipelineError("Koordinat polygon harus berupa angka.", 422, "INVALID_ZONE_CONFIG") from exc
            if not math.isfinite(x) or not math.isfinite(y) or not 0 <= x <= 1 or not 0 <= y <= 1:
                raise VisionPipelineError("Koordinat polygon ternormalisasi harus berada pada rentang 0–1.", 422, "INVALID_ZONE_CONFIG")
            points.append([x, y])
        try:
            threshold_int = int(threshold)
        except (TypeError, ValueError) as exc:
            raise VisionPipelineError("occupancy_threshold harus berupa integer positif.", 422, "INVALID_ZONE_CONFIG") from exc
        if threshold_int < 1 or threshold_int > 1000 or str(threshold_int) != str(threshold).strip():
            raise VisionPipelineError("occupancy_threshold harus berupa integer 1–1000.", 422, "INVALID_ZONE_CONFIG")
        seen.add(zone_id)
        normalized.append({
            "zone_id": zone_id,
            "name": name,
            "polygon_normalized": points,
            "occupancy_threshold": threshold_int,
        })
    return normalized


def database_path() -> Path:
    configured = os.getenv("VISION_TWIN_DB_PATH", "artifacts/vision_twin.sqlite3").strip()
    path = Path(configured).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def artifact_directory() -> Path:
    configured = os.getenv("VISION_ARTIFACT_DIR", "artifacts/vision_frames").strip()
    path = Path(configured).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    path.mkdir(parents=True, exist_ok=True)
    return path


def connect_db() -> sqlite3.Connection:
    connection = sqlite3.connect(str(database_path()), timeout=15)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS vision_jobs (
            job_id TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            source_label TEXT NOT NULL,
            original_filename TEXT NOT NULL,
            input_sha256 TEXT NOT NULL,
            opencv_version TEXT NOT NULL,
            detector TEXT,
            created_at TEXT NOT NULL,
            finished_at TEXT,
            duration_seconds REAL,
            source_fps REAL,
            source_width INTEGER,
            source_height INTEGER,
            sampled_frames INTEGER NOT NULL DEFAULT 0,
            zone_config_json TEXT NOT NULL,
            result_json TEXT,
            peak_frame_path TEXT,
            error_code TEXT,
            error_message TEXT
        );
        CREATE TABLE IF NOT EXISTS vision_observations (
            observation_id TEXT PRIMARY KEY,
            job_id TEXT NOT NULL REFERENCES vision_jobs(job_id) ON DELETE CASCADE,
            zone_id TEXT NOT NULL,
            frame_index INTEGER NOT NULL,
            video_time_seconds REAL NOT NULL,
            processed_at TEXT NOT NULL,
            occupancy_count INTEGER NOT NULL,
            occupancy_threshold INTEGER NOT NULL,
            triggered INTEGER NOT NULL,
            evidence_path TEXT NOT NULL,
            detections_json TEXT NOT NULL,
            UNIQUE(job_id, zone_id, frame_index)
        );
        CREATE TABLE IF NOT EXISTS vision_zone_state (
            zone_id TEXT PRIMARY KEY,
            zone_name TEXT NOT NULL,
            occupancy_count INTEGER NOT NULL,
            peak_count INTEGER NOT NULL,
            occupancy_threshold INTEGER NOT NULL,
            status TEXT NOT NULL,
            last_observed_at TEXT NOT NULL,
            job_id TEXT NOT NULL REFERENCES vision_jobs(job_id),
            evidence_path TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS vision_events (
            event_id TEXT PRIMARY KEY,
            job_id TEXT NOT NULL REFERENCES vision_jobs(job_id) ON DELETE CASCADE,
            zone_id TEXT NOT NULL,
            occupancy_peak INTEGER NOT NULL,
            occupancy_threshold INTEGER NOT NULL,
            status TEXT NOT NULL,
            details_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(job_id, zone_id)
        );
        CREATE TABLE IF NOT EXISTS vision_agent_runs (
            run_id TEXT PRIMARY KEY,
            job_id TEXT NOT NULL REFERENCES vision_jobs(job_id) ON DELETE CASCADE,
            event_id TEXT REFERENCES vision_events(event_id) ON DELETE SET NULL,
            status TEXT NOT NULL,
            started_at TEXT NOT NULL,
            finished_at TEXT NOT NULL,
            decision TEXT NOT NULL,
            steps_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS vision_agent_steps (
            step_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES vision_agent_runs(run_id) ON DELETE CASCADE,
            order_index INTEGER NOT NULL,
            tool_name TEXT NOT NULL,
            inputs_json TEXT NOT NULL,
            output_json TEXT NOT NULL,
            reason TEXT NOT NULL,
            status TEXT NOT NULL,
            duration_ms REAL
        );
        CREATE TABLE IF NOT EXISTS vision_tickets (
            ticket_id TEXT PRIMARY KEY,
            event_id TEXT NOT NULL REFERENCES vision_events(event_id) ON DELETE CASCADE,
            job_id TEXT NOT NULL REFERENCES vision_jobs(job_id) ON DELETE CASCADE,
            zone_id TEXT NOT NULL,
            summary TEXT NOT NULL,
            recommended_action TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            reviewed_at TEXT,
            reviewer_label TEXT,
            review_note TEXT
        );
        """
    )
    connection.commit()
    return connection


def _dict_rows(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    return [dict(row) for row in rows]


def _event_from_row(row: sqlite3.Row) -> dict[str, Any]:
    value = dict(row)
    try:
        value["details"] = json.loads(value.pop("details_json"))
    except (json.JSONDecodeError, TypeError):
        value["details"] = {}
    return value


def _ticket_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return dict(row)


def create_job(
    job_id: str,
    source_label: str,
    original_filename: str,
    input_sha256: str,
    cv_version: str,
    zone_config: list[dict[str, Any]],
) -> None:
    with closing(connect_db()) as db:
        db.execute(
            """INSERT INTO vision_jobs
            (job_id, status, source_label, original_filename, input_sha256, opencv_version,
             created_at, zone_config_json)
             VALUES (?, 'processing', ?, ?, ?, ?, ?, ?)""",
            (job_id, source_label, original_filename, input_sha256, cv_version, utc_now(), json.dumps(zone_config)),
        )
        db.commit()


def save_observation(
    db: sqlite3.Connection,
    job_id: str,
    zone: dict[str, Any],
    frame_index: int,
    video_time_seconds: float,
    occupancy_count: int,
    zone_detections: list[dict[str, Any]],
    evidence_path: Path,
    current_count: int,
    peak_count: int,
) -> None:
    now = utc_now()
    db.execute(
        """INSERT INTO vision_observations
        (observation_id, job_id, zone_id, frame_index, video_time_seconds, processed_at,
         occupancy_count, occupancy_threshold, triggered, evidence_path, detections_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            str(uuid.uuid4()), job_id, zone["zone_id"], frame_index, video_time_seconds, now,
            occupancy_count, zone["occupancy_threshold"], int(occupancy_count >= zone["occupancy_threshold"]),
            str(evidence_path), json.dumps(zone_detections, separators=(",", ":")),
        ),
    )
    db.execute(
        """INSERT INTO vision_zone_state
        (zone_id, zone_name, occupancy_count, peak_count, occupancy_threshold, status,
         last_observed_at, job_id, evidence_path)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(zone_id) DO UPDATE SET
          zone_name=excluded.zone_name, occupancy_count=excluded.occupancy_count,
          peak_count=excluded.peak_count, occupancy_threshold=excluded.occupancy_threshold,
          status=excluded.status, last_observed_at=excluded.last_observed_at,
          job_id=excluded.job_id, evidence_path=excluded.evidence_path""",
        (
            zone["zone_id"], zone["name"], current_count, peak_count, zone["occupancy_threshold"],
            "review" if current_count >= zone["occupancy_threshold"] else "normal",
            now, job_id, str(evidence_path),
        ),
    )


def _point_in_polygon(point: tuple[int, int], polygon: np.ndarray) -> bool:
    return cv2.pointPolygonTest(polygon, point, False) >= 0


def _assign_to_zones(
    frame: np.ndarray, detections: list[dict[str, Any]], zones: list[dict[str, Any]]
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, np.ndarray]]:
    height, width = frame.shape[:2]
    polygons: dict[str, np.ndarray] = {}
    for zone in zones:
        vertices = [
            [round(x * (width - 1)), round(y * (height - 1))]
            for x, y in zone["polygon_normalized"]
        ]
        polygons[zone["zone_id"]] = np.asarray(vertices, dtype=np.int32).reshape((-1, 1, 2))
    mapped = {zone["zone_id"]: [] for zone in zones}
    for detection in detections:
        x = int(detection["x"] + detection["width"] / 2)
        y = int(detection["y"] + detection["height"])
        point = (max(0, min(width - 1, x)), max(0, min(height - 1, y)))
        for zone in zones:
            if _point_in_polygon(point, polygons[zone["zone_id"]]):
                mapped[zone["zone_id"]].append(detection)
                break
    return mapped, polygons


def _annotate_video_frame(
    frame: np.ndarray,
    detections: list[dict[str, Any]],
    mapped: dict[str, list[dict[str, Any]]],
    zones: list[dict[str, Any]],
    polygons: dict[str, np.ndarray],
) -> np.ndarray:
    annotated = frame.copy()
    for zone in zones:
        polygon = polygons[zone["zone_id"]]
        colour = (50, 210, 150) if len(mapped[zone["zone_id"]]) < zone["occupancy_threshold"] else (60, 80, 240)
        cv2.polylines(annotated, [polygon], True, colour, 2, cv2.LINE_AA)
        x, y = polygon.reshape(-1, 2)[0]
        caption = f"{zone['name']}: {len(mapped[zone['zone_id']])}/{zone['occupancy_threshold']}"
        cv2.putText(annotated, caption[:80], (int(x) + 4, max(20, int(y) + 18)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, colour, 2, cv2.LINE_AA)
    for detection in detections:
        x, y = int(detection["x"]), int(detection["y"])
        x2, y2 = x + int(detection["width"]), y + int(detection["height"])
        cv2.rectangle(annotated, (x, y), (x2, y2), (50, 210, 150), 2)
        cv2.putText(annotated, "person", (x, max(18, y - 5)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (50, 210, 150), 2, cv2.LINE_AA)
    return annotated


def _summarize_agent_for_zone(
    db: sqlite3.Connection,
    job_id: str,
    zone: dict[str, Any],
    samples: list[dict[str, Any]],
    input_sha256: str,
) -> tuple[dict[str, Any] | None, dict[str, Any], dict[str, Any] | None]:
    threshold = zone["occupancy_threshold"]
    zone_id = zone["zone_id"]
    peak = max((sample["zone_counts"][zone_id] for sample in samples), default=0)
    current = samples[-1]["zone_counts"][zone_id] if samples else 0
    run_id = str(uuid.uuid4())
    started = utc_now()
    steps: list[dict[str, Any]] = []
    last_step_perf = time.perf_counter()

    def record(tool: str, inputs: dict[str, Any], output: dict[str, Any], reason: str) -> None:
        nonlocal last_step_perf
        index = len(steps) + 1
        step_perf = time.perf_counter()
        duration_ms = round((step_perf - last_step_perf) * 1000.0, 3)
        last_step_perf = step_perf
        step = {
            "step_id": str(uuid.uuid4()),
            "order": index,
            "tool": tool,
            "status": "completed",
            "inputs": inputs,
            "output": output,
            "reason": reason,
            "timestamp": utc_now(),
            "duration_ms": duration_ms,
        }
        steps.append(step)

    record(
        "get_zone_state",
        {"zone_id": zone_id, "job_id": job_id},
        {"current_count": current, "peak_count": peak, "threshold": threshold, "samples": len(samples)},
        "Agent membaca state twin dan observasi yang baru disimpan.",
    )

    triggered_indices = [
        index for index, sample in enumerate(samples)
        if sample["zone_counts"][zone_id] >= threshold
    ]
    event: dict[str, Any] | None = None
    ticket: dict[str, Any] | None = None
    decision = "no_action"

    if not triggered_indices:
        record(
            "policy_no_action",
            {"zone_id": zone_id, "threshold": threshold},
            {"triggered": False, "current_count": current, "peak_count": peak},
            "Tidak ada sampel yang mencapai ambang konfigurasi; tidak perlu tiket.",
        )
    else:
        trigger_index = triggered_indices[0]
        event_id = str(uuid.uuid4())
        trigger_sample = samples[trigger_index]
        details = {
            "source_type": "uploaded_video",
            "zone_name": zone["name"],
            "trigger_frame_index": trigger_sample["frame_index"],
            "trigger_video_time_seconds": trigger_sample["time_seconds"],
            "peak_count": peak,
            "threshold": threshold,
            "current_count": current,
            "input_sha256": input_sha256,
        }
        db.execute(
            """INSERT INTO vision_events
            (event_id, job_id, zone_id, occupancy_peak, occupancy_threshold, status, details_json, created_at)
            VALUES (?, ?, ?, ?, ?, 'observed', ?, ?)""",
            (event_id, job_id, zone_id, peak, threshold, json.dumps(details), utc_now()),
        )
        event = {"event_id": event_id, "job_id": job_id, "zone_id": zone_id,
                 "occupancy_peak": peak, "occupancy_threshold": threshold,
                 "status": "observed", "details": details, "created_at": utc_now()}
        decision = "request_human_review"
        window_size = 2
        first_window = samples[trigger_index : trigger_index + window_size]
        next_window = samples[trigger_index + window_size : trigger_index + window_size * 2]
        first_peak = max((sample["zone_counts"][zone_id] for sample in first_window), default=0)
        next_peak = max((sample["zone_counts"][zone_id] for sample in next_window), default=None)

        record(
            "analyze_next_window",
            {
                "event_id": event_id, "zone_id": zone_id,
                "start_frame_index": trigger_sample["frame_index"],
                "frame_count": window_size,
            },
            {
                "first_window_samples": len(first_window),
                "first_window_peak": first_peak,
                "followup_samples": len(next_window),
                "followup_peak": next_peak,
                "threshold": threshold,
                "persistent": bool(next_window) and next_peak is not None and next_peak >= threshold,
            },
            "Pemeriksaan lanjutan memakai sampel video yang diproses sesudah trigger pertama.",
        )

        if next_window and next_peak is not None and next_peak >= threshold:
            record(
                "compare_snapshots",
                {"event_id": event_id, "zone_id": zone_id},
                {
                    "first_window_peak": first_peak,
                    "followup_window_peak": next_peak,
                    "difference": next_peak - first_peak,
                    "threshold": threshold,
                    "condition_persisted": True,
                },
                "Ambang tetap terlampaui pada jendela lanjutan; policy mengizinkan penyusunan draf, bukan aksi otomatis.",
            )
            ticket_id = str(uuid.uuid4())
            summary = f"Indikasi okupansi zona {zone['name']} mencapai {peak} orang pada video uji."
            recommended_action = "Petugas memverifikasi frame bukti, keadaan area, dan konfigurasi ambang sebelum tindak lanjut."
            db.execute(
                """INSERT INTO vision_tickets
                (ticket_id, event_id, job_id, zone_id, summary, recommended_action, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, 'pending_approval', ?)""",
                (ticket_id, event_id, job_id, zone_id, summary, recommended_action, utc_now()),
            )
            db.execute("UPDATE vision_events SET status='ticket_draft' WHERE event_id=?", (event_id,))
            ticket = {
                "ticket_id": ticket_id, "event_id": event_id, "job_id": job_id,
                "zone_id": zone_id, "summary": summary, "recommended_action": recommended_action,
                "status": "pending_approval", "created_at": utc_now(),
                "reviewed_at": None, "reviewer_label": None, "review_note": None,
            }
            record(
                "draft_ticket",
                {"event_id": event_id, "zone_id": zone_id, "peak_count": peak},
                {"ticket_id": ticket_id, "status": "pending_approval", "external_action_executed": False},
                "Bukti berulang melewati ambang; hanya draf persetujuan yang dibuat dan tidak ada sistem luar yang diubah.",
            )
            event["status"] = "ticket_draft"
            decision = "draft_ticket_pending_approval"
            db.execute(
                "UPDATE vision_zone_state SET status='review' WHERE zone_id=? AND job_id=?",
                (zone_id, job_id),
            )
        else:
            reason = (
                "Belum ada jendela lanjutan setelah trigger; evidence tidak cukup untuk menyatakan kondisi persisten."
                if not next_window
                else "Sampel lanjutan tidak mengonfirmasi ambang; petugas perlu meninjau apakah lonjakan hanya sementara."
            )
            record(
                "request_human_review",
                {"event_id": event_id, "zone_id": zone_id, "threshold": threshold},
                {"event_status": "pending_review", "ticket_created": False},
                reason,
            )
            db.execute("UPDATE vision_events SET status='pending_review' WHERE event_id=?", (event_id,))
            event["status"] = "pending_review"
            decision = "human_review_required"
            db.execute(
                "UPDATE vision_zone_state SET status='review' WHERE zone_id=? AND job_id=?",
                (zone_id, job_id),
            )

    finished = utc_now()
    db.execute(
        """INSERT INTO vision_agent_runs
        (run_id, job_id, event_id, status, started_at, finished_at, decision, steps_json)
        VALUES (?, ?, ?, 'completed', ?, ?, ?, ?)""",
        (run_id, job_id, event["event_id"] if event else None, started, finished, decision, json.dumps(steps)),
    )
    for step in steps:
        db.execute(
            """INSERT INTO vision_agent_steps
            (step_id, run_id, order_index, tool_name, inputs_json, output_json, reason, status, duration_ms)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (step["step_id"], run_id, step["order"], step["tool"], json.dumps(step["inputs"]),
             json.dumps(step["output"]), step["reason"], step["status"], step["duration_ms"]),
        )
    db.commit()

    run = {
        "run_id": run_id, "job_id": job_id, "event_id": event["event_id"] if event else None,
        "status": "completed", "started_at": started, "finished_at": finished,
        "decision": decision, "steps": steps,
    }
    return event, run, ticket


def process_video_file(
    video_path: str,
    original_filename: str,
    source_label: str,
    input_sha256: str,
    zones: list[dict[str, Any]],
    sample_interval_seconds: int = 1,
) -> dict[str, Any]:
    """Process an uploaded short clip and persist its evidence, twin state, and agent trace."""
    cv_version = ensure_opencv_version()
    job_id = str(uuid.uuid4())
    started_perf = time.perf_counter()
    original_filename = Path(original_filename).name[:200] or "uploaded-video"
    source_label = source_label.strip()[:100] or "Uploaded video"

    capture = cv2.VideoCapture(video_path)
    if not capture.isOpened():
        capture.release()
        raise VisionPipelineError("Video tidak dapat dibuka. Periksa codec atau format file.", 422, "VIDEO_DECODE_FAILED")

    fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
    frame_total = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    source_width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    source_height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    if source_width < 1 or source_height < 1:
        capture.release()
        raise VisionPipelineError("Metadata resolusi video tidak valid.", 422, "VIDEO_METADATA_INVALID")
    if source_width * source_height > MAX_FRAME_PIXELS:
        capture.release()
        raise VisionPipelineError("Resolusi video terlalu besar.", 413, "VIDEO_RESOLUTION_TOO_LARGE")
    if fps <= 0 or not math.isfinite(fps):
        fps = 25.0
    duration = frame_total / fps if frame_total > 0 else None
    if duration is not None and duration > MAX_VIDEO_SECONDS:
        capture.release()
        raise VisionPipelineError("Durasi video melebihi batas 5 menit.", 413, "VIDEO_TOO_LONG")

    effective_interval = max(float(sample_interval_seconds), (duration or 0.0) / MAX_SAMPLES)
    stride = max(1, round(fps * effective_interval))
    effective_interval = stride / fps

    try:
        detector_name, detector = make_person_detector()
    except FileNotFoundError as exc:
        capture.release()
        raise VisionPipelineError("Model ONNX pada VISION_MODEL_PATH tidak ditemukan.", 503, "VISION_MODEL_UNAVAILABLE") from exc
    except (cv2.error, ValueError) as exc:
        capture.release()
        raise VisionPipelineError("Model detector tidak dapat dimuat.", 503, "VISION_MODEL_INVALID") from exc

    create_job(job_id, source_label, original_filename, input_sha256, cv_version, zones)
    job_artifact_dir = artifact_directory() / job_id
    job_artifact_dir.mkdir(parents=True, exist_ok=True)
    samples: list[dict[str, Any]] = []
    peak_frame_path: Path | None = None
    global_peak = -1
    frame_index = -1
    sampled_count = 0

    try:
        with closing(connect_db()) as db:
            while True:
                ok, raw_frame = capture.read()
                if not ok:
                    break
                frame_index += 1
                if frame_index % stride != 0:
                    continue

                height, width = raw_frame.shape[:2]
                if width * height > MAX_FRAME_PIXELS:
                    raise VisionPipelineError("Frame melebihi batas resolusi yang diizinkan.", 413, "VIDEO_RESOLUTION_TOO_LARGE")
                resize_scale = min(1.0, MAX_FRAME_SIDE / max(width, height))
                frame = raw_frame
                if resize_scale < 1.0:
                    frame = cv2.resize(
                        raw_frame,
                        (max(1, round(width * resize_scale)), max(1, round(height * resize_scale))),
                        interpolation=cv2.INTER_AREA,
                    )
                detections = detector(frame)
                mapped, polygons = _assign_to_zones(frame, detections, zones)
                annotated = _annotate_video_frame(frame, detections, mapped, zones, polygons)
                image_path = job_artifact_dir / f"frame-{frame_index:08d}.jpg"
                success = cv2.imwrite(str(image_path), annotated, [int(cv2.IMWRITE_JPEG_QUALITY), 78])
                if not success:
                    raise VisionPipelineError("Gagal menyimpan frame bukti.", 500, "EVIDENCE_WRITE_FAILED")

                counts = {zone["zone_id"]: len(mapped[zone["zone_id"]]) for zone in zones}
                sample = {
                    "frame_index": frame_index,
                    "time_seconds": round(frame_index / fps, 3),
                    "zone_counts": counts,
                    "evidence_filename": image_path.name,
                }
                samples.append(sample)
                sampled_count += 1
                for zone in zones:
                    zone_id = zone["zone_id"]
                    zone_count = counts[zone_id]
                    zone_peak = max((item["zone_counts"][zone_id] for item in samples), default=zone_count)
                    zone_detections = mapped[zone_id]
                    save_observation(
                        db, job_id, zone, frame_index, frame_index / fps, zone_count,
                        zone_detections, image_path, zone_count, zone_peak,
                    )
                total_count = sum(counts.values())
                if total_count > global_peak:
                    global_peak = total_count
                    peak_frame_path = image_path

                if sampled_count >= MAX_SAMPLES:
                    break
            capture.release()
            db.commit()

        if not samples:
            raise VisionPipelineError("Video tidak memiliki frame yang dapat diproses.", 422, "VIDEO_HAS_NO_FRAMES")

        event_results: list[dict[str, Any]] = []
        agent_runs: list[dict[str, Any]] = []
        ticket_results: list[dict[str, Any]] = []
        with closing(connect_db()) as db:
            for zone in zones:
                event, run, ticket = _summarize_agent_for_zone(db, job_id, zone, samples, input_sha256)
                if event:
                    event_results.append(event)
                agent_runs.append(run)
                if ticket:
                    ticket_results.append(ticket)

            zone_summaries: list[dict[str, Any]] = []
            for zone in zones:
                zone_id = zone["zone_id"]
                counts = [sample["zone_counts"][zone_id] for sample in samples]
                latest = counts[-1]
                peak = max(counts)
                triggering = peak >= zone["occupancy_threshold"]
                zone_summaries.append({
                    "zone_id": zone_id,
                    "name": zone["name"],
                    "occupancy_count": latest,
                    "peak_count": peak,
                    "occupancy_threshold": zone["occupancy_threshold"],
                    "triggered": triggering,
                    "status": "review" if triggering else "normal",
                })
            result = {
                "source_type": "uploaded_video",
                "data_label": "OBSERVED_FROM_UPLOADED_VIDEO",
                "opencv_version": cv_version,
                "detector": detector_name,
                "source_label": source_label,
                "original_filename": original_filename,
                "input_sha256": input_sha256,
                "duration_seconds": round(duration or samples[-1]["time_seconds"], 3),
                "source_fps": round(fps, 3),
                "source_width": source_width,
                "source_height": source_height,
                "processed_width": min(source_width, MAX_FRAME_SIDE),
                "processed_height": min(source_height, MAX_FRAME_SIDE),
                "sample_interval_seconds": round(effective_interval, 3),
                "sampled_frames": sampled_count,
                "zone_summary": zone_summaries,
                "samples": samples,
                "events": event_results,
                "agent_runs": agent_runs,
                "tickets": ticket_results,
                "preview_frame_url": f"/api/vision/jobs/{job_id}/frame",
                "limitations": [
                    "Video unggahan diproses setelah diterima; ini bukan feed CCTV live dan tidak menjamin latency real-time.",
                    "Polygon zona harus dikalibrasi terhadap sudut pandang video. Zona default hanya demonstrasi dan bukan peta geometris kampus.",
                    "Occupancy adalah hitungan deteksi pada sampel frame, bukan identitas unik atau occupancy terkalibrasi.",
                    "Tidak ada tiket eksternal atau kontrol fasilitas yang dieksekusi; draft membutuhkan human approval.",
                    "Bukti hanya mewakili video yang diunggah dan konfigurasi detector/polygon yang digunakan.",
                ],
            }
            elapsed = time.perf_counter() - started_perf
            db.execute(
                """UPDATE vision_jobs SET status='completed', finished_at=?, duration_seconds=?,
                   detector=?, source_fps=?, source_width=?, source_height=?, sampled_frames=?,
                   result_json=?, peak_frame_path=?, error_code=NULL, error_message=NULL WHERE job_id=?""",
                (
                    utc_now(), elapsed, detector_name, fps, source_width, source_height, sampled_count,
                    json.dumps(result, separators=(",", ":")), str(peak_frame_path) if peak_frame_path else None, job_id,
                ),
            )
            db.commit()

        result["job_id"] = job_id
        result["status"] = "completed"
        result["duration_processing_seconds"] = round(elapsed, 4)
        return result
    except Exception as exc:
        logger.exception("Vision Twin video processing failed (job_id=%s, error_type=%s)", job_id, type(exc).__name__)
        capture.release()
        elapsed = time.perf_counter() - started_perf
        error_code = exc.code if isinstance(exc, VisionPipelineError) else "VISION_PROCESSING_FAILED"
        safe_message = str(exc) if isinstance(exc, VisionPipelineError) else "Pemrosesan video gagal. Periksa format file dan konfigurasi detector."
        with closing(connect_db()) as db:
            db.execute(
                """UPDATE vision_jobs SET status='failed', finished_at=?, duration_seconds=?,
                   sampled_frames=?, error_code=?, error_message=? WHERE job_id=?""",
                (utc_now(), elapsed, sampled_count, error_code, safe_message, job_id),
            )
            db.commit()
        if isinstance(exc, VisionPipelineError):
            raise
        raise VisionPipelineError(safe_message, 500, error_code) from exc


def get_recent_jobs(limit: int = 10) -> list[dict[str, Any]]:
    with closing(connect_db()) as db:
        rows = db.execute(
            """SELECT job_id, status, source_label, original_filename, opencv_version, detector,
                      created_at, finished_at, sampled_frames, error_code, error_message
               FROM vision_jobs ORDER BY created_at DESC LIMIT ?""",
            (max(1, min(50, limit)),),
        ).fetchall()
    return _dict_rows(rows)
def get_job(job_id: str) -> dict[str, Any] | None:
    with closing(connect_db()) as db:
        row = db.execute("SELECT * FROM vision_jobs WHERE job_id=?", (job_id,)).fetchone()
        if row is None:
            return None
        job = dict(row)
        result = json.loads(job["result_json"]) if job.get("result_json") else None
        if result:
            result.pop("samples", None)
            result.pop("preview_frame_url", None)
        return {
            "job_id": job["job_id"], "status": job["status"],
            "source_label": job["source_label"], "original_filename": job["original_filename"],
            "input_sha256": job["input_sha256"], "opencv_version": job["opencv_version"],
            "detector": job["detector"], "created_at": job["created_at"], "finished_at": job["finished_at"],
            "duration_processing_seconds": job["duration_seconds"], "sampled_frames": job["sampled_frames"],
            "error_code": job["error_code"], "error_message": job["error_message"],
            "result": result, "preview_available": bool(job.get("peak_frame_path")),
        }


def get_preview_path(job_id: str) -> Path | None:
    with closing(connect_db()) as db:
        row = db.execute("SELECT peak_frame_path FROM vision_jobs WHERE job_id=? AND status='completed'", (job_id,)).fetchone()
    if row is None or not row["peak_frame_path"]:
        return None
    path = Path(row["peak_frame_path"]).resolve()
    root = artifact_directory().resolve()
    if root not in path.parents or not path.is_file():
        return None
    return path


def get_twin_state() -> list[dict[str, Any]]:
    stale_seconds = 600
    try:
        stale_seconds = max(30, min(86400, int(os.getenv("VISION_STATE_STALE_SECONDS", "600"))))
    except ValueError:
        pass
    now = datetime.now(timezone.utc)
    with closing(connect_db()) as db:
        rows = db.execute("SELECT * FROM vision_zone_state ORDER BY zone_id").fetchall()
    result: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        last = item.pop("last_observed_at")
        try:
            last_dt = datetime.fromisoformat(last)
            age = max(0, (now - last_dt).total_seconds())
        except (ValueError, TypeError):
            age = None
        status = item["status"]
        if age is None or age > stale_seconds:
            status = "stale"
        item["status"] = status
        item["last_observed_at"] = last
        item["age_seconds"] = round(age, 1) if age is not None else None
        item.pop("evidence_path", None)
        result.append(item)
    return result


def get_events(limit: int = 50) -> list[dict[str, Any]]:
    with closing(connect_db()) as db:
        rows = db.execute("SELECT * FROM vision_events ORDER BY created_at DESC LIMIT ?", (max(1, min(200, limit)),)).fetchall()
    return [_event_from_row(row) for row in rows]


def get_agent_run_for_job(job_id: str) -> list[dict[str, Any]]:
    with closing(connect_db()) as db:
        rows = db.execute("SELECT * FROM vision_agent_runs WHERE job_id=? ORDER BY started_at", (job_id,)).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["steps"] = json.loads(item.pop("steps_json"))
        result.append(item)
    return result


def get_tickets(limit: int = 50) -> list[dict[str, Any]]:
    with closing(connect_db()) as db:
        rows = db.execute("SELECT * FROM vision_tickets ORDER BY created_at DESC LIMIT ?", (max(1, min(200, limit)),)).fetchall()
    return [_ticket_from_row(row) for row in rows]


def decide_ticket(ticket_id: str, decision: str, reviewer_label: str, note: str | None) -> dict[str, Any] | None:
    if decision not in {"approve", "reject"}:
        raise VisionPipelineError("Decision harus approve atau reject.", 422, "INVALID_TICKET_DECISION")
    label = reviewer_label.strip()[:80] or "Campus operator"
    safe_note = (note or "").strip()[:500] or None
    new_status = "approved" if decision == "approve" else "rejected"
    with closing(connect_db()) as db:
        row = db.execute("SELECT * FROM vision_tickets WHERE ticket_id=?", (ticket_id,)).fetchone()
        if row is None:
            return None
        if row["status"] != "pending_approval":
            raise VisionPipelineError("Draf ini sudah direview dan tidak dapat diputuskan ulang.", 409, "TICKET_ALREADY_REVIEWED")
        reviewed_at = utc_now()
        db.execute(
            "UPDATE vision_tickets SET status=?, reviewed_at=?, reviewer_label=?, review_note=? WHERE ticket_id=?",
            (new_status, reviewed_at, label, safe_note, ticket_id),
        )
        event_status = "approved" if decision == "approve" else "rejected"
        db.execute("UPDATE vision_events SET status=? WHERE event_id=?", (event_status, row["event_id"]))
        db.commit()
        updated = db.execute("SELECT * FROM vision_tickets WHERE ticket_id=?", (ticket_id,)).fetchone()
        return _ticket_from_row(updated)
