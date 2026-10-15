#!/usr/bin/env python3
"""Verify the installed OpenCV major version and smoke-test image/video decode."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2
import numpy as np


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", type=Path, help="Optional licensed test video to decode.")
    parser.add_argument("--output", type=Path, default=Path("artifacts/evaluations/opencv-smoke.jpg"))
    parser.add_argument("--required-major", type=int, default=5)
    args = parser.parse_args()

    version = str(cv2.__version__)
    try:
        major = int(version.split(".", maxsplit=1)[0])
    except ValueError:
        print("ERROR: Cannot parse OpenCV version:", version, file=sys.stderr)
        return 2

    build_info = cv2.getBuildInformation()
    print("OpenCV version:", version)
    print("Required major:", args.required_major)
    print("Build information available:", bool(build_info))
    print("VideoCapture backend availability:", hasattr(cv2, "VideoCapture"))
    if major != args.required_major:
        print(f"ERROR: Expected OpenCV {args.required_major}.x, found {version}.", file=sys.stderr)
        return 2

    if args.video:
        capture = cv2.VideoCapture(str(args.video))
        if not capture.isOpened():
            print("ERROR: Could not open test video:", args.video, file=sys.stderr)
            return 3
        ok, frame = capture.read()
        capture.release()
        if not ok or frame is None:
            print("ERROR: Video opened but no frame could be decoded.", file=sys.stderr)
            return 3
    else:
        # Validate the OpenCV decode/encode pathway without inventing a dataset result.
        frame = np.zeros((120, 160, 3), dtype=np.uint8)
        cv2.putText(frame, "OpenCV smoke test", (8, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1)
        encoded_ok, encoded = cv2.imencode(".png", frame)
        if not encoded_ok or cv2.imdecode(encoded, cv2.IMREAD_COLOR) is None:
            print("ERROR: Image encode/decode smoke test failed.", file=sys.stderr)
            return 3

    args.output.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(args.output), frame):
        print("ERROR: Failed to write smoke-test frame:", args.output, file=sys.stderr)
        return 3
    print("PASS: OpenCV version and frame decode/encode verified.")
    print("Smoke-test image:", args.output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
