"""Authenticated API routes for the video-backed Vision Twin MVP."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from src.auth import require_api_key
from src.twin_video import (
    DEFAULT_ZONES, VisionPipelineError, artifact_directory, decide_ticket,
    ensure_opencv_version, get_agent_run_for_job, get_events, get_job,
    get_preview_path, get_tickets, get_twin_state, parse_zones, process_video_file,
)

router = APIRouter(prefix="/api/vision", tags=["vision-twin"], dependencies=[Depends(require_api_key)])
MAX_VIDEO_UPLOAD_BYTES = 50 * 1024 * 1024
ALLOWED_VIDEO_TYPES = {
    "video/mp4": ".mp4", "video/quicktime": ".mov", "video/x-msvideo": ".avi",
    "video/webm": ".webm", "video/mpeg": ".mpeg", "application/octet-stream": None,
}
ALLOWED_VIDEO_SUFFIXES = {".mp4", ".mov", ".avi", ".webm", ".mpeg", ".mpg", ".m4v"}


class TicketDecision(BaseModel):
    decision: Literal["approve", "reject"]
    reviewer_label: str = Field(default="Campus operator", min_length=1, max_length=80)
    note: str | None = Field(default=None, max_length=500)


@router.get("/opencv-version", summary="Verify OpenCV runtime version")
def vision_opencv_version() -> dict[str, Any]:
    import cv2

    version = str(cv2.__version__)
    required = os.getenv("VISION_REQUIRE_OPENCV5", "true").strip().lower() not in {"0", "false", "no", "off"}
    try:
        ensure_opencv_version()
        compatible = True
        message = "Runtime memenuhi kebijakan versi OpenCV."
    except VisionPipelineError as exc:
        compatible = False
        message = str(exc)
    return {
        "opencv_version": version, "required_major": 5 if required else None,
        "compatible": compatible, "message": message,
        "build_information_available": bool(cv2.getBuildInformation()),
    }


@router.get("/zones", summary="Get the starter normalized polygon zones")
def list_vision_zones() -> dict[str, Any]:
    return {
        "source_type": "demo_configuration",
        "data_label": "DEMO",
        "coordinate_system": "normalized frame coordinates, 0–1",
        "zones": DEFAULT_ZONES,
        "warning": "Polygon default adalah konfigurasi demo. Kalibrasikan terhadap sudut pandang video sebelum menafsirkan occupancy.",
    }


@router.post("/videos", status_code=201, summary="Analyze an uploaded video and update Vision Twin state")
async def analyze_video(
    file: UploadFile = File(...),
    source_label: str = Form(default="Uploaded video", min_length=1, max_length=100),
    zones_json: str = Form(default=json.dumps(DEFAULT_ZONES)),
    sample_interval_seconds: int = Form(default=1, ge=1, le=30),
) -> dict[str, Any]:
    """Run the synchronous video MVP; persist observations, zone state, events, and agent traces."""
    try:
        ensure_opencv_version()
        zones = parse_zones(zones_json)
    except VisionPipelineError as exc:
        await file.close()
        raise HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": str(exc)}) from exc

    original_name = Path(file.filename or "upload.mp4").name
    suffix = Path(original_name).suffix.lower()
    content_type = (file.content_type or "").split(";", maxsplit=1)[0].strip().lower()
    if suffix not in ALLOWED_VIDEO_SUFFIXES:
        suffix_from_type = ALLOWED_VIDEO_TYPES.get(content_type)
        if suffix_from_type is None:
            await file.close()
            raise HTTPException(status_code=415, detail="Format video tidak didukung. Gunakan MP4, MOV, AVI, WebM, atau MPEG.")
        suffix = suffix_from_type
    if content_type and content_type not in ALLOWED_VIDEO_TYPES:
        await file.close()
        raise HTTPException(status_code=415, detail="Tipe konten bukan video yang didukung.")

    temp_path: str | None = None
    digest = hashlib.sha256()
    total_bytes = 0
    try:
        fd, temp_path = tempfile.mkstemp(prefix="nexus-vision-", suffix=suffix)
        os.close(fd)
        with open(temp_path, "wb") as output:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                total_bytes += len(chunk)
                if total_bytes > MAX_VIDEO_UPLOAD_BYTES:
                    raise HTTPException(status_code=413, detail="Ukuran video melebihi batas 50 MiB.")
                digest.update(chunk)
                output.write(chunk)
        if total_bytes == 0:
            raise HTTPException(status_code=400, detail="File video kosong.")
        result = await run_in_threadpool(
            process_video_file, temp_path, original_name, source_label, digest.hexdigest(), zones, sample_interval_seconds
        )
        return result
    except VisionPipelineError as exc:
        raise HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": str(exc)}) from exc
    finally:
        await file.close()
        if temp_path:
            try:
                os.unlink(temp_path)
            except FileNotFoundError:
                pass


@router.get("/jobs/{job_id}", summary="Read persisted Vision Twin job summary")
def read_vision_job(job_id: str) -> dict[str, Any]:
    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Vision job tidak ditemukan.")
    if job.get("preview_available"):
        job["preview_frame_url"] = f"/api/vision/jobs/{job_id}/frame"
    return job


@router.get("/jobs/{job_id}/frame", summary="Read the annotated peak-evidence frame")
def read_vision_job_frame(job_id: str) -> FileResponse:
    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Vision job tidak ditemukan.")
    path = get_preview_path(job_id)
    if path is None:
        raise HTTPException(status_code=404, detail="Frame bukti tidak tersedia.")
    return FileResponse(path, media_type="image/jpeg", filename=f"vision-evidence-{job_id}.jpg")


@router.get("/twin/state", summary="Read the latest per-zone digital twin state")
def read_twin_state() -> dict[str, Any]:
    return {
        "data_label": "OBSERVED_FROM_UPLOADED_VIDEO",
        "source_type": "persisted_video_observations",
        "zones": get_twin_state(),
        "note": "State berasal dari video unggahan terakhir per zona; tidak menggambarkan CCTV live.",
    }


@router.get("/events", summary="List persisted vision events")
def read_vision_events(limit: int = 50) -> dict[str, Any]:
    return {"events": get_events(limit), "data_label": "OBSERVED_FROM_UPLOADED_VIDEO"}


@router.get("/jobs/{job_id}/agent-runs", summary="Read the job agent decision traces")
def read_vision_agent_runs(job_id: str) -> dict[str, Any]:
    if get_job(job_id) is None:
        raise HTTPException(status_code=404, detail="Vision job tidak ditemukan.")
    return {"job_id": job_id, "runs": get_agent_run_for_job(job_id)}


@router.get("/tickets", summary="List draft tickets waiting for human review")
def read_vision_tickets(limit: int = 50) -> dict[str, Any]:
    return {"tickets": get_tickets(limit)}


@router.post("/tickets/{ticket_id}/decision", summary="Approve or reject a vision-generated draft ticket")
def review_vision_ticket(ticket_id: str, payload: TicketDecision) -> dict[str, Any]:
    try:
        ticket = decide_ticket(ticket_id, payload.decision, payload.reviewer_label, payload.note)
    except VisionPipelineError as exc:
        raise HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": str(exc)}) from exc
    if ticket is None:
        raise HTTPException(status_code=404, detail="Draf tiket tidak ditemukan.")
    return {"ticket": ticket, "external_action_executed": False}
