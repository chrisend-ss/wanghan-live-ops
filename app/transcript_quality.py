"""Independent, inspectable ASR gates. Scores are heuristics, not probabilities."""
from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional

ASR_PASS_THRESHOLD = 0.72
BOILERPLATE = {
    "subtitle_credit": re.compile(
        r"(?:中文)?字幕\s*(?:志愿者|翻译|制作|校对|由.{0,16}提供)|"
        r"subtitles?\s*(?:by|provided|translated)", re.I),
    "distribution_credit": re.compile(
        r"独播剧场|television\s+series\s+exclusive|exclusive\s+broadcast", re.I),
    "subscription_credit": re.compile(
        r"(?:点赞.{0,8}订阅.{0,8}(?:转发|分享).{0,12}(?:打赏|支持))|"
        r"明镜.{0,16}(?:订阅|栏目)|(?:订阅|支持).{0,16}明镜", re.I),
}


def normalize_text(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKC", text).casefold()
                   if c.isalnum())


def metric(row: Dict[str, Any], name: str) -> Optional[float]:
    try:
        value = float(row[name])
        return value if math.isfinite(value) else None
    except (KeyError, TypeError, ValueError):
        return None


def _duration(row: Dict[str, Any]) -> float:
    return max(0.0, float(row["end_seconds"]) - float(row["start_seconds"]))


def _internal_loop(text: str) -> bool:
    # Full-string periodicity detects novel decoder loops without a phrase list.
    if len(text) < 12:
        return False
    for width in range(1, min(24, len(text) // 4) + 1):
        unit = text[:width]
        expected = (unit * (len(text) // width + 1))[:len(text)]
        if text == expected:
            return True
    return False


def audit_asr_quality(
    rows: List[Dict[str, Any]], *, pass_threshold: float = ASR_PASS_THRESHOLD,
) -> Dict[str, Any]:
    if not 0 < pass_threshold <= 1:
        raise ValueError("asr_pass_threshold must be in (0, 1]")
    speech = [r for r in rows if r.get("kind") == "speech"]
    texts = [normalize_text(str(r.get("text", ""))) for r in speech]
    exact = defaultdict(list)
    grams = defaultdict(set)
    for index, text in enumerate(texts):
        exact[text].append(index)
        if len(text) >= 18:
            for pos in range(len(text) - 11):
                grams[text[pos:pos + 12]].add(index)

    def distant(indexes):
        times = sorted(float(speech[i]["start_seconds"]) for i in indexes)
        return len(times) >= 3 and times[-1] - times[0] >= 60

    recurring = {g for g, indexes in grams.items() if distant(indexes)}
    reasons = Counter()
    statuses = Counter()
    audits = []
    for index, (row, compact) in enumerate(zip(speech, texts)):
        text = str(row.get("text", ""))
        duration = _duration(row)
        logprob = metric(row, "avg_logprob")
        no_speech = metric(row, "no_speech_prob")
        compression = metric(row, "compression_ratio")
        score = 1.0
        quality = []
        hard = []
        review = []
        if logprob is None or no_speech is None:
            quality.append("missing_model_evidence")
            score = min(score, 0.50)
        if logprob is not None:
            if logprob > 0:
                quality.append("invalid_logprob")
                score = 0.0
            elif logprob < -1.0:
                quality.append("low_logprob")
                score -= 0.5
            elif logprob < -0.7:
                quality.append("borderline_logprob")
                score -= 0.25
        if no_speech is not None:
            if not 0 <= no_speech <= 1:
                quality.append("invalid_no_speech_probability")
                score = 0.0
            elif no_speech >= 0.6:
                quality.append("high_no_speech_probability")
                score -= 0.6
            elif no_speech >= 0.3:
                quality.append("borderline_no_speech_probability")
                score -= 0.3
        if compression is not None and compression > 2.4:
            quality.append("high_compression_ratio")
            score -= 0.35
        if not compact or duration <= 0:
            quality.append("empty_or_invalid_segment")
            score = 0.0
        elif len(compact) == 1:
            quality.append("single_character")
            score -= 0.3
        if duration > 0 and len(compact) / duration > 10:
            quality.append("implausible_text_rate")
            score -= 0.4
        if duration > 12 and len(compact) / duration < 0.5:
            quality.append("sparse_text")
            score -= 0.35

        hard.extend(name for name, pattern in BOILERPLATE.items() if pattern.search(text))
        if _internal_loop(compact):
            # Real cheers also repeat. A loop alone is a review signal.
            review.append("internal_text_loop")
        occurrences = exact[compact]
        if len(compact) >= 16 and distant(occurrences):
            review.append("distant_exact_repeat")
        windows = {compact[p:p + 12] for p in range(max(0, len(compact) - 11))}
        coverage = len(windows & recurring) / max(1, len(windows))
        if len(compact) >= 18 and coverage >= 0.65:
            review.append("distant_recurring_template")
        anomalous = bool(quality) and score < pass_threshold
        if review and anomalous:
            hard.append("repetition_with_model_or_rate_anomaly")
        status = "rejected" if hard else "review" if review else "clear"
        if status == "rejected":
            score = min(score, 0.10)
        elif status == "review":
            score = min(score, pass_threshold - 0.01)
        score = round(max(0.0, min(1.0, score)), 3)
        passed = score >= pass_threshold and status == "clear" and bool(compact)
        row.update({
            "asr_quality_score": score,
            "asr_confidence": "high" if score >= 0.9 else "medium" if passed else "low",
            "asr_quality_pass": passed,
            "asr_quality_reasons": quality,
            "hallucination_status": status,
            "hallucination_detected": status == "rejected",
            "hallucination_reasons": list(dict.fromkeys(hard + review)),
        })
        statuses[status] += 1
        reasons.update(row["hallucination_reasons"])
        if status != "clear":
            audits.append({
                "segment_index": index, "start_seconds": row["start_seconds"],
                "end_seconds": row["end_seconds"], "text": text,
                "status": status, "reasons": row["hallucination_reasons"],
                "exact_occurrences": len(occurrences), "template_coverage": round(coverage, 3),
            })
    passed = sum(r["asr_quality_pass"] for r in speech)
    return {
        "asr_quality": {
            "scored_count": len(speech), "passed_count": passed,
            "excluded_count": len(speech) - passed, "pass_threshold": pass_threshold,
            "score_semantics": "heuristic_quality_gate_not_accuracy_probability",
            "independent_of_speaker_confidence": True,
            "model_evidence_coverage": {
                name: sum(metric(r, name) is not None for r in speech)
                for name in ("avg_logprob", "no_speech_prob", "compression_ratio")
            },
            "reason_counts": dict(Counter(x for r in speech for x in r["asr_quality_reasons"])),
        },
        "hallucination_audit": {
            "distribution": {key: statuses[key] for key in ("clear", "review", "rejected")},
            "reason_counts": dict(reasons), "raw_text_preserved": True,
            "entries": audits,
        },
    }


def verified_wanghan(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [r for r in rows if r.get("kind") == "speech"
            and r.get("speaker_verification") == "wanghan"
            and r.get("speaker_verification_pass") is True
            and r.get("asr_quality_pass") is True
            and r.get("hallucination_status") == "clear"
            and str(r.get("text", "")).strip()]
