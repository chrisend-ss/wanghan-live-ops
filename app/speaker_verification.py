"""Three-way reference verification without full-recording speaker clustering."""
from __future__ import annotations

import math
from collections import Counter
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

VERIFY_THRESHOLD = 0.72
REJECT_THRESHOLD = 0.45
MIN_SECONDS = 1.5


def validate_thresholds(verify: float, reject: float) -> None:
    if not (math.isfinite(verify) and math.isfinite(reject) and -1 <= reject < verify <= 1):
        raise ValueError("speaker thresholds require -1 <= reject < verify <= 1")


def classify_scores(scores: Sequence[float], *, verify: float, reject: float) -> str:
    validate_thresholds(verify, reject)
    if not scores or not all(math.isfinite(s) for s in scores):
        return "uncertain"
    # All subwindows must agree. Mixed/alternating speakers stay uncertain.
    if min(scores) >= verify:
        return "wanghan"
    if max(scores) <= reject:
        return "non_wanghan"
    return "uncertain"


def _windows(start: float, end: float) -> List[tuple[float, float]]:
    duration = end - start
    if duration < MIN_SECONDS:
        return []
    count = max(1, math.ceil(duration / 4))
    return [(start + duration * i / count, start + duration * (i + 1) / count)
            for i in range(count)]


def _speech_coverage(start: float, end: float, zones) -> float:
    # Zones from the segmenter do not overlap. Use unpadded speech evidence.
    if not zones or end <= start:
        return 0.0
    intervals = sorted((max(start, z.start), min(end, z.end)) for z in zones
                       if z.label in {"speech", "male", "female"}
                       and z.end > start and z.start < end)
    covered = 0.0
    cursor = start
    for left, right in intervals:
        covered += max(0.0, right - max(cursor, left))
        cursor = max(cursor, right)
    return covered / (end - start)


def verify_speakers(
    rows: List[Dict[str, Any]], *, ranges: Optional[Sequence[Sequence[float]]] = None,
    reference_confirmed: bool = False, verify_threshold: float = VERIFY_THRESHOLD,
    reject_threshold: float = REJECT_THRESHOLD, zones=None,
    embedding: Optional[Callable[[float, float], Any]] = None,
) -> Dict[str, Any]:
    validate_thresholds(verify_threshold, reject_threshold)
    for row in rows:
        row.update({"speaker": "说话人_不确定", "speaker_confidence": "low",
                    "speaker_cluster": None, "speaker_verification": "uncertain",
                    "speaker_verification_pass": False, "speaker_similarity": None,
                    "speaker_verification_reason": "reference_not_confirmed"})
    summary = {
        "mode": "same_recording_reference_verification",
        "reference_confirmed": reference_confirmed, "reference_usable": False,
        "reference_ranges": list(ranges or []),
        "thresholds": {"verify": verify_threshold, "reject": reject_threshold},
        "score_semantics": "cosine_similarity_not_identity_accuracy_probability",
        "full_recording_clustering_used": False, "voiceprint_persisted": False,
        "reference_scope": "same_recording_in_memory_only",
    }

    def finish(reason):
        summary["reference_status"] = reason
        counts = Counter(r["speaker_verification"] for r in rows)
        summary["distribution"] = {key: counts[key] for key in ("wanghan", "non_wanghan", "uncertain")}
        summary["duration_seconds"] = {
            key: round(sum(max(0.0, float(r["end_seconds"]) - float(r["start_seconds"]))
                           for r in rows if r["speaker_verification"] == key), 3)
            for key in ("wanghan", "non_wanghan", "uncertain")}
        return summary

    if not reference_confirmed or not ranges:
        return finish("missing_or_unconfirmed")
    parsed = []
    for pair in ranges:
        if len(pair) != 2:
            return finish("invalid_reference_range")
        start, end = map(float, pair)
        if not (math.isfinite(start) and math.isfinite(end) and start >= 0 and 3 <= end - start <= 12):
            return finish("reference_must_be_3_to_12_seconds")
        if _speech_coverage(start, end, zones) < 0.90:
            return finish("reference_not_clean_speech")
        parsed.append((start, end))
    parsed.sort()
    if len(parsed) < 2 or any(parsed[i][1] > parsed[i + 1][0] for i in range(len(parsed) - 1)):
        return finish("need_two_independent_nonoverlapping_references")
    if embedding is None:
        return finish("embedding_backend_unavailable")

    import numpy as np

    def encode(start, end):
        try:
            raw = embedding(start, end)
            if raw is None:
                return None
            vector = np.asarray(raw, dtype=float).reshape(-1)
            norm = np.linalg.norm(vector)
            if not np.isfinite(vector).all() or norm <= 1e-9:
                return None
            return vector / norm
        except Exception:
            return None

    refs = []
    for start, end in parsed:
        for left, right in _windows(start, end):
            vector = encode(left, right)
            if vector is None:
                return finish("reference_embedding_failed")
            refs.append(vector)
    try:
        matrix = np.vstack(refs)
        pairs = (matrix @ matrix.T)[np.triu_indices(len(refs), 1)]
    except ValueError:
        return finish("reference_embedding_shape_mismatch")
    summary["reference_min_pair_similarity"] = round(float(pairs.min()), 4)
    # Inconsistent references fail closed; never silently select a convenient cluster.
    if float(pairs.min()) < 0.60:
        return finish("reference_inconsistent_or_mixed")
    summary["reference_usable"] = True
    failures = 0
    for row in rows:
        start, end = float(row["start_seconds"]), float(row["end_seconds"])
        windows = _windows(start, end)
        if not windows or _speech_coverage(start, end, zones) < 0.85:
            row["speaker_verification_reason"] = "short_or_mixed_audio"
            continue
        scores = []
        reference_disagreement = False
        for left, right in windows:
            vector = encode(left, right)
            if vector is None:
                scores = []
                failures += 1
                break
            try:
                values = matrix @ vector
            except ValueError:
                scores = []
                failures += 1
                break
            scores.append(float(np.median(values)))
            if float(values.max() - values.min()) > 0.25:
                reference_disagreement = True
        label = classify_scores(scores, verify=verify_threshold, reject=reject_threshold)
        if reference_disagreement:
            label = "uncertain"
        row.update({
            "speaker": {"wanghan": "王焓", "non_wanghan": "非王焓", "uncertain": "说话人_不确定"}[label],
            "speaker_verification": label, "speaker_verification_pass": label == "wanghan",
            "speaker_similarity": round(float(np.mean(scores)), 4) if scores else None,
            "speaker_similarity_min": round(min(scores), 4) if scores else None,
            "speaker_similarity_max": round(max(scores), 4) if scores else None,
            "speaker_confidence": "medium" if label != "uncertain" else "low",
            "speaker_verification_reason": "reference_disagreement" if reference_disagreement
                else "embedding_failed" if not scores else "reference_" + label,
        })
    summary["embedding_failure_count"] = failures
    return finish("usable")
