from __future__ import annotations

import cv2
import numpy as np
import pytest


def _make_test_video(path, frames=12, fps=5.0):
    writer = cv2.VideoWriter(
        str(path),
        cv2.VideoWriter_fourcc(*"MJPG"),
        fps,
        (100, 80),
    )
    if not writer.isOpened():
        pytest.skip("OpenCV runtime does not provide an MJPG VideoWriter for test fixtures.")
    for index in range(frames):
        frame = np.zeros((80, 100, 3), dtype=np.uint8)
        cv2.putText(frame, str(index), (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        writer.write(frame)
    writer.release()
    return path.read_bytes()


def _whole_frame_zone(threshold=1):
    import json
    return json.dumps([
        {
            "zone_id": "zone-test",
            "name": "Test Zone",
            "polygon_normalized": [[0, 0], [1, 0], [1, 1], [0, 1]],
            "occupancy_threshold": threshold,
        }
    ])


def _auth(api_key):
    return {"X-API-Key": api_key}


def test_video_twin_requires_auth(client, tmp_path, monkeypatch):
    video = _make_test_video(tmp_path / "auth-test.avi")
    response = client.post(
        "/api/vision/videos",
        data={"source_label": "test", "zones_json": _whole_frame_zone()},
        files={"file": ("auth-test.avi", video, "video/x-msvideo")},
    )
    assert response.status_code == 401


def test_video_twin_rejects_unsupported_extension(client, api_key):
    response = client.post(
        "/api/vision/videos",
        headers=_auth(api_key),
        data={"source_label": "test", "zones_json": _whole_frame_zone()},
        files={"file": ("notes.txt", b"not a video", "text/plain")},
    )
    assert response.status_code == 415


def test_video_twin_rejects_invalid_zone_config(client, api_key, tmp_path, monkeypatch):
    video = _make_test_video(tmp_path / "bad-zone.avi")
    response = client.post(
        "/api/vision/videos",
        headers=_auth(api_key),
        data={"source_label": "test", "zones_json": "not-json"},
        files={"file": ("bad-zone.avi", video, "video/x-msvideo")},
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "INVALID_ZONE_CONFIG"


def test_video_twin_persists_state_trace_and_ticket_for_persistent_trigger(
    client, api_key, tmp_path, monkeypatch
):
    from src import twin_video

    monkeypatch.setenv("VISION_TWIN_DB_PATH", str(tmp_path / "twin.sqlite3"))
    monkeypatch.setenv("VISION_ARTIFACT_DIR", str(tmp_path / "frames"))
    monkeypatch.setenv("VISION_REQUIRE_OPENCV5", "true")
    monkeypatch.setattr(
        twin_video,
        "make_person_detector",
        lambda: (
            "test detector",
            lambda frame: [{"x": 20, "y": 10, "width": 10, "height": 40, "label": "person"}],
        ),
    )
    video = _make_test_video(tmp_path / "persistent-trigger.avi")

    response = client.post(
        "/api/vision/videos",
        headers=_auth(api_key),
        data={
            "source_label": "E2E test clip",
            "zones_json": _whole_frame_zone(threshold=1),
            "sample_interval_seconds": "1",
        },
        files={"file": ("persistent-trigger.avi", video, "video/x-msvideo")},
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "completed"
    assert body["source_type"] == "uploaded_video"
    assert body["data_label"] == "OBSERVED_FROM_UPLOADED_VIDEO"
    assert body["opencv_version"].split(".")[0] == "5"
    assert body["sampled_frames"] >= 3
    assert body["zone_summary"][0]["peak_count"] == 1
    assert body["zone_summary"][0]["status"] == "review"
    assert body["events"][0]["status"] == "ticket_draft"
    assert body["agent_runs"][0]["decision"] == "draft_ticket_pending_approval"
    assert [step["tool"] for step in body["agent_runs"][0]["steps"]] == [
        "get_zone_state",
        "analyze_next_window",
        "compare_snapshots",
        "draft_ticket",
    ]
    assert body["tickets"][0]["status"] == "pending_approval"

    state = client.get("/api/vision/twin/state", headers=_auth(api_key))
    assert state.status_code == 200
    assert state.json()["zones"][0]["occupancy_count"] == 1

    runs = client.get(f"/api/vision/jobs/{body['job_id']}/agent-runs", headers=_auth(api_key))
    assert runs.status_code == 200
    assert runs.json()["runs"][0]["decision"] == "draft_ticket_pending_approval"

    jobs = client.get("/api/vision/jobs?limit=5", headers=_auth(api_key))
    assert jobs.status_code == 200
    assert any(item["job_id"] == body["job_id"] for item in jobs.json()["jobs"])

    frame = client.get(f"/api/vision/jobs/{body['job_id']}/frame", headers=_auth(api_key))
    assert frame.status_code == 200
    assert frame.headers["content-type"].startswith("image/jpeg")

    ticket_id = body["tickets"][0]["ticket_id"]
    approved = client.post(
        f"/api/vision/tickets/{ticket_id}/decision",
        headers=_auth(api_key),
        json={"decision": "approve", "reviewer_label": "test operator", "note": "checked"},
    )
    assert approved.status_code == 200
    assert approved.json()["ticket"]["status"] == "approved"
    assert approved.json()["external_action_executed"] is False

    repeated = client.post(
        f"/api/vision/tickets/{ticket_id}/decision",
        headers=_auth(api_key),
        json={"decision": "reject", "reviewer_label": "test operator"},
    )
    assert repeated.status_code == 409


def test_video_twin_uses_evidence_to_avoid_ticket_when_clear(
    client, api_key, tmp_path, monkeypatch
):
    from src import twin_video

    monkeypatch.setenv("VISION_TWIN_DB_PATH", str(tmp_path / "clear-twin.sqlite3"))
    monkeypatch.setenv("VISION_ARTIFACT_DIR", str(tmp_path / "clear-frames"))
    monkeypatch.setenv("VISION_REQUIRE_OPENCV5", "true")
    monkeypatch.setattr(twin_video, "make_person_detector", lambda: ("test detector", lambda frame: []))
    video = _make_test_video(tmp_path / "clear.avi")

    response = client.post(
        "/api/vision/videos",
        headers=_auth(api_key),
        data={"source_label": "Clear clip", "zones_json": _whole_frame_zone(threshold=1)},
        files={"file": ("clear.avi", video, "video/x-msvideo")},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["events"] == []
    assert body["tickets"] == []
    assert body["agent_runs"][0]["decision"] == "no_action"
    assert body["agent_runs"][0]["steps"][1]["tool"] == "policy_no_action"


def test_opencv_version_gate_rejects_non_five_major(monkeypatch):
    from src import twin_video

    monkeypatch.setenv("VISION_REQUIRE_OPENCV5", "true")
    monkeypatch.setattr(twin_video, "opencv_version", lambda: "4.10.0")
    with pytest.raises(twin_video.VisionPipelineError) as error:
        twin_video.ensure_opencv_version()
    assert error.value.code == "OPENCV_VERSION_MISMATCH"
