import cv2
import numpy as np


def _png_bytes():
    image = np.zeros((120, 160, 3), dtype=np.uint8)
    ok, encoded = cv2.imencode(".png", image)
    assert ok
    return encoded.tobytes()


def test_vision_endpoint_requires_auth(client):
    response = client.post(
        "/api/vision/pedestrians",
        data={"zone_id": "zone-A1", "camera_label": "Test"},
        files={"file": ("frame.png", _png_bytes(), "image/png")},
    )
    assert response.status_code == 401


def test_vision_endpoint_rejects_unsupported_content_type(client, api_key):
    response = client.post(
        "/api/vision/pedestrians",
        headers={"X-API-Key": api_key},
        data={"zone_id": "zone-A1", "camera_label": "Test"},
        files={"file": ("frame.gif", b"GIF89a", "image/gif")},
    )
    assert response.status_code == 415


def test_vision_endpoint_rejects_invalid_image(client, api_key):
    response = client.post(
        "/api/vision/pedestrians",
        headers={"X-API-Key": api_key},
        data={"zone_id": "zone-A1", "camera_label": "Test"},
        files={"file": ("frame.png", b"not-an-image", "image/png")},
    )
    assert response.status_code == 400


def test_vision_endpoint_returns_detections_and_provenance(client, api_key, monkeypatch):
    from src import vision_api

    monkeypatch.setattr(
        vision_api,
        "detect_people",
        lambda frame: (
            [{"x": 3, "y": 5, "width": 20, "height": 40, "label": "person"}],
            "test OpenCV detector",
        ),
    )
    monkeypatch.setattr(vision_api, "_annotate", lambda frame, detections: "data:image/jpeg;base64,dGVzdA==")

    response = client.post(
        "/api/vision/pedestrians",
        headers={"X-API-Key": api_key},
        data={"zone_id": "zone-A1", "camera_label": "Unit test image"},
        files={"file": ("frame.png", _png_bytes(), "image/png")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["source_type"] == "uploaded_image"
    assert body["data_label"] == "OBSERVED_FROM_UPLOADED_IMAGE"
    assert body["zone_id"] == "zone-A1"
    assert body["camera_label"] == "Unit test image"
    assert body["detector"] == "test OpenCV detector"
    assert body["people_count"] == 1
    assert body["detections"] == [{"x": 3, "y": 5, "width": 20, "height": 40, "label": "person"}]
    assert body["annotated_image"].startswith("data:image/jpeg;base64,")
    assert any("bukan stream CCTV live" in item for item in body["limitations"])


def test_vision_endpoint_enforces_upload_size(client, api_key):
    response = client.post(
        "/api/vision/pedestrians",
        headers={"X-API-Key": api_key},
        data={"zone_id": "zone-A1", "camera_label": "Large file"},
        files={"file": ("large.png", b"x" * (8 * 1024 * 1024 + 1), "image/png")},
    )
    assert response.status_code == 413
