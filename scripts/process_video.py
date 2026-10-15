#!/usr/bin/env python3
"""Run the repository's video-to-twin pipeline from the command line."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from src.twin_video import VisionPipelineError, parse_zones, process_video_file


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video", type=Path, help="Local test video with appropriate usage rights.")
    parser.add_argument("--source-label", default="CLI demo video")
    parser.add_argument("--zones", type=Path, help="Optional JSON file containing 1–4 normalized zones.")
    parser.add_argument("--sample-interval", type=int, default=1, choices=range(1, 31))
    parser.add_argument("--output", type=Path, help="Path for the complete result JSON.")
    args = parser.parse_args()

    if not args.video.is_file():
        print("ERROR: Input video not found.", file=sys.stderr)
        return 2
    try:
        zones_json = args.zones.read_text(encoding="utf-8") if args.zones else None
        zones = parse_zones(zones_json)
        digest = hashlib.sha256()
        with args.video.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        result = process_video_file(
            str(args.video.resolve()),
            args.video.name,
            args.source_label,
            digest.hexdigest(),
            zones,
            args.sample_interval,
        )
    except (OSError, json.JSONDecodeError, VisionPipelineError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    output_path = args.output or Path("artifacts/evaluations") / (result["job_id"] + ".json")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print("Job ID:", result["job_id"])
    print("OpenCV:", result["opencv_version"])
    print("Detector:", result["detector"])
    print("Sampled frames:", result["sampled_frames"])
    print("Result JSON:", output_path.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
