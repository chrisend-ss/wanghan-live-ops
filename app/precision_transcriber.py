from __future__ import annotations

import gc
import json
import math
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
import soundfile as sf

from .bilibili_browser import _download_candidate, get_page_media

DEFAULT_GLOSSARY = (
    "王焓，听潮阁，焓太医，中医，开灯，连麦，PK，粉丝团，音浪，"
    "十万粉，古风，直播伴侣，排档，榜单，不周山"
)


def _ffmpeg_to_wav(source_path: Path, wav_path: Path) -> None:
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(source_path),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-c:a",
            "pcm_s16le",
            str(wav_path),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _download_best_audio(url: str, tmp: Path, stem: str = "source") -> Tuple[Dict[str, Any], Path, str]:
    media = get_page_media(url)
    last_error: Optional[Exception] = None
    for index, (candidate_url, kind, _) in enumerate(media["candidates"][:8]):
        try:
            suffix = ".m4s" if kind == "audio" else ".mp4"
            source_path = tmp / f"{stem}_{index}{suffix}"
            _download_candidate(
                candidate_url,
                source_path,
                url,
                media["cookies"],
            )
            if source_path.stat().st_size < 1024:
                raise RuntimeError("Downloaded media is unexpectedly small")
            wav_path = tmp / f"{stem}_{index}.wav"
            _ffmpeg_to_wav(source_path, wav_path)
            return media, wav_path, kind
        except Exception as exc:
            last_error = exc
    raise RuntimeError(f"All page media candidates failed: {last_error}")


def _segment_audio_classes(wav_path: Path) -> Tuple[List[Dict[str, Any]], str]:
    """Return speech/music/noise regions.

    inaSpeechSegmenter is preferred because it explicitly separates music from
    speech. This is important for livestream recordings where Whisper otherwise
    hallucinates lyrics/background audio as host speech.
    """
    try:
        from inaSpeechSegmenter import Segmenter

        segmenter = Segmenter(vad_engine="smn", detect_gender=False)
        raw = segmenter(str(wav_path))
        events: List[Dict[str, Any]] = []
        for label, start, end in raw:
            label_text = str(label).lower()
            if label_text in {"male", "female"}:
                label_text = "speech"
            if label_text not in {"speech", "music", "noise", "noenergy"}:
                label_text = "unknown"
            events.append(
                {
                    "audio_class": label_text,
                    "start_seconds": float(start),
                    "end_seconds": float(end),
                    "source": "inaSpeechSegmenter",
                }
            )
        return events, "inaSpeechSegmenter"
    except Exception as exc:
        # Precision mode must degrade honestly. If the classifier is unavailable,
        # do not pretend music has been separated.
        data, sr = sf.read(str(wav_path), dtype="float32", always_2d=False)
        duration = len(data) / float(sr)
        return (
            [
                {
                    "audio_class": "unknown",
                    "start_seconds": 0.0,
                    "end_seconds": duration,
                    "source": "classifier_fallback",
                    "error": f"{type(exc).__name__}: {exc}",
                }
            ],
            "classifier_fallback",
        )


def _merge_speech_regions(
    events: Sequence[Dict[str, Any]],
    gap_seconds: float = 0.35,
    max_seconds: float = 28.0,
    pad_seconds: float = 0.15,
) -> List[Tuple[float, float]]:
    speech = [
        (float(e["start_seconds"]), float(e["end_seconds"]))
        for e in events
        if e.get("audio_class") == "speech"
    ]
    if not speech:
        return []

    merged: List[Tuple[float, float]] = []
    start, end = speech[0]
    for s, e in speech[1:]:
        if s - end <= gap_seconds and e - start <= max_seconds:
            end = e
        else:
            merged.append((max(0.0, start - pad_seconds), end + pad_seconds))
            start, end = s, e
    merged.append((max(0.0, start - pad_seconds), end + pad_seconds))

    split: List[Tuple[float, float]] = []
    for s, e in merged:
        cur = s
        while e - cur > max_seconds:
            split.append((cur, cur + max_seconds))
            cur += max_seconds
        if e - cur >= 0.35:
            split.append((cur, e))
    return split


def _slice_audio(audio: np.ndarray, sr: int, start: float, end: float) -> np.ndarray:
    lo = max(0, int(round(start * sr)))
    hi = min(len(audio), int(round(end * sr)))
    return np.asarray(audio[lo:hi], dtype=np.float32)


def _clean_text(text: str) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    text = re.sub(r"(.)\1{6,}", r"\1\1\1", text)
    return text


def _looks_repetitive(text: str) -> bool:
    t = re.sub(r"\s+", "", text)
    if len(t) < 12:
        return False
    for n in (2, 3, 4, 5, 6):
        if len(t) >= n * 4:
            unit = t[:n]
            if unit * (len(t) // n) in t:
                return True
    return False


def _transcribe_one(
    model: Any,
    audio_slice: np.ndarray,
    language: str,
    glossary: str,
    beam_size: int,
) -> Dict[str, Any]:
    seg_iter, info = model.transcribe(
        audio_slice,
        language=language,
        beam_size=beam_size,
        temperature=0.0,
        condition_on_previous_text=False,
        vad_filter=False,
        word_timestamps=True,
        initial_prompt=glossary,
    )
    pieces: List[str] = []
    avg_logprobs: List[float] = []
    no_speech_probs: List[float] = []
    compression_ratios: List[float] = []
    for seg in seg_iter:
        text = _clean_text(seg.text)
        if text:
            pieces.append(text)
        if getattr(seg, "avg_logprob", None) is not None:
            avg_logprobs.append(float(seg.avg_logprob))
        if getattr(seg, "no_speech_prob", None) is not None:
            no_speech_probs.append(float(seg.no_speech_prob))
        if getattr(seg, "compression_ratio", None) is not None:
            compression_ratios.append(float(seg.compression_ratio))

    text = _clean_text("".join(pieces))
    avg_logprob = float(np.mean(avg_logprobs)) if avg_logprobs else None
    no_speech_prob = float(np.max(no_speech_probs)) if no_speech_probs else None
    compression_ratio = float(np.max(compression_ratios)) if compression_ratios else None

    low_quality = (
        not text
        or (avg_logprob is not None and avg_logprob < -0.72)
        or (no_speech_prob is not None and no_speech_prob > 0.55)
        or (compression_ratio is not None and compression_ratio > 2.4)
        or _looks_repetitive(text)
    )
    if avg_logprob is None:
        confidence = "unknown"
    elif avg_logprob >= -0.35 and not low_quality:
        confidence = "high"
    elif avg_logprob >= -0.72 and not low_quality:
        confidence = "medium"
    else:
        confidence = "low"

    return {
        "text": text,
        "avg_logprob": avg_logprob,
        "no_speech_prob": no_speech_prob,
        "compression_ratio": compression_ratio,
        "confidence": confidence,
        "low_quality": low_quality,
        "detected_language": getattr(info, "language", language),
    }


def _parse_time_value(value: Any) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    parts = text.split(":")
    if len(parts) == 3:
        h, m, s = parts
        return int(h) * 3600 + int(m) * 60 + float(s)
    if len(parts) == 2:
        m, s = parts
        return int(m) * 60 + float(s)
    return float(text)


def _speaker_verifier() -> Any:
    from speechbrain.inference.speaker import SpeakerRecognition

    return SpeakerRecognition.from_hparams(
        source="speechbrain/spkrec-ecapa-voxceleb",
        savedir="~/.cache/wanghan/speechbrain-spkrec-ecapa-voxceleb",
        run_opts={"device": "cpu"},
    )


def _build_reference_audio(
    current_url: str,
    current_audio: np.ndarray,
    current_sr: int,
    reference: Optional[Dict[str, Any]],
    tmp: Path,
) -> Optional[np.ndarray]:
    if not reference:
        return None
    ranges = reference.get("ranges") or []
    if not ranges:
        return None

    ref_url = str(reference.get("url") or current_url).strip()
    if ref_url == current_url:
        ref_audio = current_audio
        ref_sr = current_sr
    else:
        _, ref_wav, _ = _download_best_audio(ref_url, tmp, stem="voice_reference")
        ref_audio, ref_sr = sf.read(str(ref_wav), dtype="float32", always_2d=False)

    chunks: List[np.ndarray] = []
    for item in ranges:
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            continue
        start = _parse_time_value(item[0])
        end = _parse_time_value(item[1])
        if end <= start:
            continue
        chunk = _slice_audio(ref_audio, ref_sr, start, end)
        if chunk.size:
            chunks.append(chunk)
    if not chunks:
        return None

    # Limit reference to ~90 s to keep verification cheap while retaining enough
    # clean host speech for robust matching.
    joined = np.concatenate(chunks)
    max_samples = int(ref_sr * 90)
    return joined[:max_samples]


def _verify_speaker(
    verifier: Any,
    reference_audio: np.ndarray,
    candidate_audio: np.ndarray,
    threshold: float,
) -> Tuple[str, Optional[float]]:
    if len(candidate_audio) < 16000:
        return "uncertain", None
    try:
        import torch

        ref = torch.from_numpy(reference_audio).float().unsqueeze(0)
        cand = torch.from_numpy(candidate_audio).float().unsqueeze(0)
        score, prediction = verifier.verify_batch(ref, cand, threshold=threshold)
        score_value = float(score.detach().cpu().reshape(-1)[0])
        is_same = bool(prediction.detach().cpu().reshape(-1)[0])
        if is_same:
            return "wanghan", score_value
        # Keep a narrow uncertain band rather than forcing every non-match into
        # another speaker. This protects against short/noisy clips.
        if score_value >= threshold - 0.05:
            return "uncertain", score_value
        return "other_speaker", score_value
    except Exception:
        return "uncertain", None


def transcribe_page_media_precision(
    url: str,
    primary_model: str = "medium",
    retry_model: str = "large-v3-turbo",
    language: str = "zh",
    glossary: str = DEFAULT_GLOSSARY,
    voice_reference: Optional[Dict[str, Any]] = None,
    speaker_threshold: float = 0.25,
) -> Dict[str, Any]:
    """High-precision Bilibili transcription for WangHan livestream review.

    Pipeline:
      media -> speech/music/noise segmentation -> speech-only ASR ->
      low-confidence selective retry -> optional WangHan speaker verification.

    It intentionally favors precision over recall. Music-only and noise regions
    are preserved as timeline events and are not converted into WangHan speech.
    """

    from faster_whisper import WhisperModel

    with tempfile.TemporaryDirectory(prefix="wanghan_precision_v2_") as tmp_dir:
        tmp = Path(tmp_dir)
        media, wav_path, source_kind = _download_best_audio(url, tmp)
        audio, sr = sf.read(str(wav_path), dtype="float32", always_2d=False)
        if sr != 16000:
            raise RuntimeError(f"Expected 16 kHz WAV, got {sr}")

        audio_events, classifier_name = _segment_audio_classes(wav_path)
        speech_regions = _merge_speech_regions(audio_events)

        # Honest fallback: if the classifier failed, let Whisper's VAD detect
        # speech but do not claim music has been separated.
        classifier_failed = classifier_name == "classifier_fallback"

        primary = WhisperModel(
            primary_model,
            device="cpu",
            compute_type="int8",
            cpu_threads=4,
        )

        rows: List[Dict[str, Any]] = []
        if classifier_failed:
            seg_iter, _ = primary.transcribe(
                str(wav_path),
                language=language,
                beam_size=5,
                temperature=0.0,
                condition_on_previous_text=False,
                vad_filter=True,
                word_timestamps=True,
                initial_prompt=glossary,
            )
            for seg in seg_iter:
                text = _clean_text(seg.text)
                if not text:
                    continue
                rows.append(
                    {
                        "start_seconds": float(seg.start),
                        "end_seconds": float(seg.end),
                        "text": text,
                        "audio_class": "unknown",
                        "asr_model": primary_model,
                        "avg_logprob": float(seg.avg_logprob),
                        "no_speech_prob": float(seg.no_speech_prob),
                        "compression_ratio": float(seg.compression_ratio),
                        "confidence": "medium" if seg.avg_logprob >= -0.72 else "low",
                        "needs_retry": bool(seg.avg_logprob < -0.72 or seg.compression_ratio > 2.4),
                    }
                )
        else:
            for start, end in speech_regions:
                clip = _slice_audio(audio, sr, start, end)
                result = _transcribe_one(primary, clip, language, glossary, beam_size=5)
                if not result["text"]:
                    continue
                rows.append(
                    {
                        "start_seconds": float(start),
                        "end_seconds": float(end),
                        "text": result["text"],
                        "audio_class": "speech",
                        "asr_model": primary_model,
                        "avg_logprob": result["avg_logprob"],
                        "no_speech_prob": result["no_speech_prob"],
                        "compression_ratio": result["compression_ratio"],
                        "confidence": result["confidence"],
                        "needs_retry": bool(result["low_quality"]),
                    }
                )

        retry_indices = [i for i, row in enumerate(rows) if row.get("needs_retry")]
        del primary
        gc.collect()

        if retry_indices and retry_model:
            retry = WhisperModel(
                retry_model,
                device="cpu",
                compute_type="int8",
                cpu_threads=4,
            )
            for index in retry_indices:
                row = rows[index]
                start = float(row["start_seconds"])
                end = float(row["end_seconds"])
                clip = _slice_audio(audio, sr, start, end)
                result = _transcribe_one(retry, clip, language, glossary, beam_size=5)
                # Prefer retry output when it improves model confidence or the
                # primary output was clearly suspicious.
                old_lp = row.get("avg_logprob")
                new_lp = result.get("avg_logprob")
                improved = (
                    result["text"]
                    and (
                        old_lp is None
                        or (new_lp is not None and new_lp > float(old_lp) + 0.05)
                        or row.get("confidence") == "low"
                    )
                )
                if improved:
                    row.update(
                        {
                            "text": result["text"],
                            "asr_model": retry_model,
                            "avg_logprob": result["avg_logprob"],
                            "no_speech_prob": result["no_speech_prob"],
                            "compression_ratio": result["compression_ratio"],
                            "confidence": result["confidence"],
                            "retry_used": True,
                        }
                    )
                else:
                    row["retry_used"] = False
            del retry
            gc.collect()

        reference_audio = _build_reference_audio(
            current_url=url,
            current_audio=audio,
            current_sr=sr,
            reference=voice_reference,
            tmp=tmp,
        )

        verifier = None
        if reference_audio is not None:
            try:
                verifier = _speaker_verifier()
            except Exception:
                verifier = None

        for row in rows:
            start = float(row["start_seconds"])
            end = float(row["end_seconds"])
            if verifier is not None and reference_audio is not None:
                candidate = _slice_audio(audio, sr, start, end)
                role, score = _verify_speaker(
                    verifier,
                    reference_audio,
                    candidate,
                    speaker_threshold,
                )
            else:
                role, score = "unknown", None
            row["speaker_role"] = role
            row["speaker_score"] = score
            row["speaker_threshold"] = speaker_threshold if verifier is not None else None
            row["source"] = f"bilibili_{media['method']}_{source_kind}_precision_v2"

        verified_wanghan = [r for r in rows if r.get("speaker_role") == "wanghan"]

        quality_report = {
            "pipeline": "precision_v2",
            "audio_classifier": classifier_name,
            "primary_model": primary_model,
            "retry_model": retry_model,
            "speaker_verification_enabled": verifier is not None,
            "speaker_threshold": speaker_threshold if verifier is not None else None,
            "speech_segment_count": len(rows),
            "verified_wanghan_segment_count": len(verified_wanghan),
            "music_region_count": sum(1 for e in audio_events if e.get("audio_class") == "music"),
            "noise_region_count": sum(
                1 for e in audio_events if e.get("audio_class") in {"noise", "noenergy"}
            ),
            "retry_segment_count": len(retry_indices),
            "low_confidence_after_retry": sum(1 for r in rows if r.get("confidence") == "low"),
            "policy": (
                "Only segments verified as speaker_role=wanghan are safe for host quotes. "
                "Music/noise is never promoted to WangHan speech. Unknown/uncertain speaker "
                "segments must remain unassigned."
            ),
        }

        return {
            "info": media["info"],
            "segments": rows,
            "audio_events": audio_events,
            "verified_wanghan_segments": verified_wanghan,
            "quality_report": quality_report,
            "source": f"bilibili_{media['method']}_{source_kind}_precision_v2",
            "needs_audio_fallback": False,
            "detected_language": language,
        }
