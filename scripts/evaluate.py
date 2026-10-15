#!/usr/bin/env python3
"""Evaluate sampled per-zone occupancy counts against a manually labelled CSV.

Ground-truth CSV columns: frame_index,zone_id,ground_truth_count.
The result JSON must be the complete POST /api/vision/videos response or the
output of scripts/process_video.py. Matching uses exact frame_index + zone_id.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from pathlib import Path
from typing import Any


def load_ground_truth(path: Path) -> dict[tuple[int, str], int]:
    values: dict[tuple[int, str], int] = {}
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        required = {"frame_index", "zone_id", "ground_truth_count"}
        if not required.issubset(set(reader.fieldnames or [])):
            raise ValueError("Ground-truth CSV needs frame_index, zone_id, ground_truth_count columns.")
        for row in reader:
            key = (int(row["frame_index"]), row["zone_id"].strip())
            count = int(row["ground_truth_count"])
            if count < 0:
                raise ValueError("Ground-truth counts must be non-negative.")
            if key in values:
                raise ValueError(f"Duplicate ground-truth key: {key}")
            values[key] = count
    return values


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", required=True, type=Path)
    parser.add_argument("--ground-truth", required=True, type=Path)
    parser.add_argument("--output", type=Path, default=Path("artifacts/evaluations/occupancy-evaluation.json"))
    args = parser.parse_args()

    try:
        result = json.loads(args.results.read_text(encoding="utf-8"))
        truth = load_ground_truth(args.ground_truth)
        thresholds = {item["zone_id"]: int(item["occupancy_threshold"]) for item in result["zone_summary"]}
        predictions: dict[tuple[int, str], int] = {}
        for sample in result["samples"]:
            for zone_id, count in sample["zone_counts"].items():
                predictions[(int(sample["frame_index"]), zone_id)] = int(count)
        common = sorted(set(truth) & set(predictions))
        if not common:
            raise ValueError("No exact frame_index + zone_id matches between results and ground truth.")
        if any(zone_id not in thresholds for _, zone_id in common):
            raise ValueError("Ground truth contains a zone absent from the result summary.")

        absolute_errors = [abs(predictions[key] - truth[key]) for key in common]
        mean_absolute_error = sum(absolute_errors) / len(absolute_errors)
        tp = fp = fn = tn = 0
        for key in common:
            zone_id = key[1]
            threshold = thresholds[zone_id]
            predicted_trigger = predictions[key] >= threshold
            truth_trigger = truth[key] >= threshold
            if predicted_trigger and truth_trigger:
                tp += 1
            elif predicted_trigger:
                fp += 1
            elif truth_trigger:
                fn += 1
            else:
                tn += 1
        precision = tp / (tp + fp) if tp + fp else None
        recall = tp / (tp + fn) if tp + fn else None
        f1 = 2 * precision * recall / (precision + recall) if precision is not None and recall is not None and precision + recall else None
        report: dict[str, Any] = {
            "job_id": result.get("job_id"),
            "source_sha256": result.get("input_sha256"),
            "opencv_version": result.get("opencv_version"),
            "detector": result.get("detector"),
            "matched_sample_zone_pairs": len(common),
            "ground_truth_pairs": len(truth),
            "prediction_pairs": len(predictions),
            "unmatched_ground_truth_pairs": len(set(truth) - set(predictions)),
            "unmatched_prediction_pairs": len(set(predictions) - set(truth)),
            "occupancy_mae": round(mean_absolute_error, 6),
            "threshold_event_confusion": {"tp": tp, "fp": fp, "fn": fn, "tn": tn},
            "threshold_event_precision": round(precision, 6) if precision is not None else None,
            "threshold_event_recall": round(recall, 6) if recall is not None else None,
            "threshold_event_f1": round(f1, 6) if f1 is not None else None,
            "limitations": [
                "Metrics describe only exact matched frame-index/zone pairs in the supplied ground truth.",
                "This count-based report does not compute bounding-box precision/recall or identify unique people.",
                "Threshold metrics inherit the configured demo occupancy threshold; this is not a safety standard.",
            ],
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        print(json.dumps(report, indent=2, ensure_ascii=False))
        print("Evaluation report:", args.output.resolve())
        return 0
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
