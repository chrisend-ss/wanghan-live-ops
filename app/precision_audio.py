from __future__ import annotations

import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import numpy as np

from .speaker_verification import REJECT_THRESHOLD, VERIFY_THRESHOLD, validate_thresholds, verify_speakers
from .transcript_quality import ASR_PASS_THRESHOLD, audit_asr_quality, verified_wanghan

PIPELINE_VERSION = "precision_v2_1"


@dataclass(frozen=True)
class AudioZone:
    label: str
    start: float
    end: float

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)


def convert_to_analysis_wav(source: Path, destination: Path) -> Path:
    """Convert arbitrary media/audio to 16 kHz mono PCM WAV."""
    cmd = [
        "ffmpeg", "-y", "-i", str(source), "-vn",
        "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(destination),
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return destination


def segment_speech_music(audio_path: Path) -> List[AudioZone]:
    """Split audio into speech/music/noise. Singing is intentionally tagged as music."""
    try:
        from inaSpeechSegmenter import Segmenter
    except ImportError as exc:
        raise RuntimeError("inaSpeechSegmenter is required for precision mode") from exc

    segmenter = Segmenter(vad_engine="smn", detect_gender=False)
    raw = segmenter(str(audio_path))
    return [AudioZone(str(label), float(start), float(end)) for label, start, end in raw]


def merge_speech_zones(
    zones: Sequence[AudioZone],
    *,
    max_gap: float = 0.35,
    min_duration: float = 0.55,
    pad: float = 0.12,
) -> List[AudioZone]:
    speech = [z for z in zones if z.label in {"speech", "male", "female"}]
    if not speech:
        return []

    merged: List[AudioZone] = []
    current = speech[0]
    for zone in speech[1:]:
        if zone.start - current.end <= max_gap:
            current = AudioZone("speech", current.start, max(current.end, zone.end))
        else:
            if current.duration >= min_duration:
                merged.append(current)
            current = zone
    if current.duration >= min_duration:
        merged.append(current)

    return [
        AudioZone("speech", max(0.0, zone.start - pad), zone.end + pad)
        for zone in merged
    ]


def _extract_wav_range(source: Path, destination: Path, start: float, end: float) -> Path:
    duration = max(0.01, end - start)
    cmd = [
        "ffmpeg", "-y", "-ss", f"{start:.3f}", "-t", f"{duration:.3f}",
        "-i", str(source), "-ac", "1", "-ar", "16000",
        "-c:a", "pcm_s16le", str(destination),
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return destination


def transcribe_speech_zones(
    audio_path: Path,
    zones: Sequence[AudioZone],
    *,
    model_size: str,
    language: str = "zh",
    hotwords: Optional[str] = None,
) -> List[Dict[str, Any]]:
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise RuntimeError("faster-whisper is required") from exc

    model = WhisperModel(
        model_size,
        device="cpu",
        compute_type="int8",
        cpu_threads=4,
    )

    output: List[Dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="wanghan_precision_asr_") as temp_dir:
        temp = Path(temp_dir)
        for idx, zone in enumerate(zones):
            clip = _extract_wav_range(
                audio_path,
                temp / f"speech_{idx:05d}.wav",
                zone.start,
                zone.end,
            )
            segments_iter, _ = model.transcribe(
                str(clip),
                language=language,
                beam_size=5,
                best_of=5,
                temperature=0.0,
                vad_filter=False,
                condition_on_previous_text=False,
                word_timestamps=False,
                no_speech_threshold=0.55,
                log_prob_threshold=-1.0,
                compression_ratio_threshold=2.4,
                initial_prompt=hotwords,
            )
            for seg in segments_iter:
                text = (seg.text or "").strip()
                if not text:
                    continue

                start = zone.start + float(seg.start)
                end = min(zone.end, zone.start + float(seg.end))
                avg_logprob = getattr(seg, "avg_logprob", None)
                no_speech_prob = getattr(seg, "no_speech_prob", None)

                output.append(
                    {
                        "start_seconds": start,
                        "end_seconds": end,
                        "text": text,
                        "avg_logprob": avg_logprob,
                        "no_speech_prob": no_speech_prob,
                        "compression_ratio": getattr(seg, "compression_ratio", None),
                        "kind": "speech",
                    }
                )
            clip.unlink(missing_ok=True)
            if idx % 10 == 0:
                print(f"ASR speech zone {idx + 1}/{len(zones)}", flush=True)
    return output




def _speaker_encoder(savedir: Path):
    try:
        from speechbrain.inference.speaker import EncoderClassifier
    except ImportError as exc:
        raise RuntimeError("speechbrain is required for speaker verification") from exc

    return EncoderClassifier.from_hparams(
        source="speechbrain/spkrec-ecapa-voxceleb",
        savedir=str(savedir),
    )




def assign_speakers(
    audio_path: Path,
    segments: List[Dict[str, Any]],
    *,
    wanghan_reference_ranges: Optional[Sequence[Sequence[float]]] = None,
    reference_confirmed: bool = False,
    verify_threshold: float = VERIFY_THRESHOLD,
    reject_threshold: float = REJECT_THRESHOLD,
    zones: Optional[Sequence[AudioZone]] = None,
) -> Dict[str, Any]:
    """Use in-memory references only; missing/unclean references fail closed."""
    encoder = None
    samples = None
    with tempfile.TemporaryDirectory(prefix="wanghan_verify_") as temp_dir:
        def embedding(start: float, end: float):
            nonlocal encoder, samples
            import soundfile as sf
            import torch
            if encoder is None:
                encoder = _speaker_encoder(Path(temp_dir) / "model")
                samples, rate = sf.read(str(audio_path), dtype="float32")
                if rate != 16000 or samples.ndim != 1:
                    raise ValueError("Verification requires 16 kHz mono audio")
            clip = samples[int(start * 16000):int(end * 16000)]
            if len(clip) < int(1.5 * 16000):
                return None
            with torch.inference_mode():
                return encoder.encode_batch(torch.from_numpy(clip).unsqueeze(0)).detach().cpu().numpy()
        summary = verify_speakers(
            segments, ranges=wanghan_reference_ranges,
            reference_confirmed=reference_confirmed,
            verify_threshold=verify_threshold, reject_threshold=reject_threshold,
            zones=zones, embedding=embedding,
        )
    return {"segments": segments, "speaker_summary": summary}


def build_precision_transcript(
    audio_path: Path,
    *,
    model_size: str = "large-v3",
    language: str = "zh",
    hotwords: Optional[str] = None,
    wanghan_reference_ranges: Optional[Sequence[Sequence[float]]] = None,
    reference_confirmed: bool = False,
    speaker_verify_threshold: float = VERIFY_THRESHOLD,
    speaker_reject_threshold: float = REJECT_THRESHOLD,
    asr_pass_threshold: float = ASR_PASS_THRESHOLD,
) -> Dict[str, Any]:
    validate_thresholds(speaker_verify_threshold, speaker_reject_threshold)
    if not 0 < asr_pass_threshold <= 1:
        raise ValueError("asr_pass_threshold must be in (0, 1]")
    zones = segment_speech_music(audio_path)
    speech_zones = merge_speech_zones(zones)

    speech_segments = transcribe_speech_zones(
        audio_path,
        speech_zones,
        model_size=model_size,
        language=language,
        hotwords=hotwords,
    )
    asr_audit = audit_asr_quality(speech_segments, pass_threshold=asr_pass_threshold)
    speaker_result = assign_speakers(
        audio_path,
        speech_segments,
        wanghan_reference_ranges=wanghan_reference_ranges,
        reference_confirmed=reference_confirmed,
        verify_threshold=speaker_verify_threshold,
        reject_threshold=speaker_reject_threshold,
        zones=zones,
    )
    speech_segments = speaker_result["segments"]
    verified = verified_wanghan(speech_segments)

    event_segments: List[Dict[str, Any]] = []
    for zone in zones:
        if zone.label == "music":
            event_segments.append(
                {
                    "start_seconds": zone.start,
                    "end_seconds": zone.end,
                    "kind": "music",
                    "speaker": "背景音乐/歌唱",
                    "text": "",
                    "speaker_confidence": "high",
                }
            )
        elif zone.label in {"noise", "noEnergy"}:
            event_segments.append(
                {
                    "start_seconds": zone.start,
                    "end_seconds": zone.end,
                    "kind": "noise",
                    "speaker": "环境声",
                    "text": "",
                    "speaker_confidence": "high",
                }
            )

    timeline = sorted(
        speech_segments + event_segments,
        key=lambda x: (
            float(x["start_seconds"]),
            float(x["end_seconds"]),
        ),
    )

    durations: Dict[str, float] = {}
    for zone in zones:
        durations[zone.label] = durations.get(zone.label, 0.0) + zone.duration

    return {
        "segments": timeline,
        "speech_segments": speech_segments,
        "zones": [
            {
                "label": z.label,
                "start_seconds": z.start,
                "end_seconds": z.end,
            }
            for z in zones
        ],
        "speaker_summary": speaker_result["speaker_summary"],
        "quality": {
            "pipeline_version": PIPELINE_VERSION,
            "speech_segment_count": len(speech_segments),
            "zone_count": len(zones),
            "duration_by_zone_seconds": {
                k: round(v, 3) for k, v in durations.items()
            },
            "model": model_size,
            "music_is_not_transcribed": True,
            "singing_is_expected_to_be_labeled_music": True,
            **asr_audit,
            "verified_transcript": {
                "segment_count": len(verified),
                "speech_seconds": round(sum(float(r["end_seconds"]) - float(r["start_seconds"])
                                            for r in verified), 3),
                "filter": "speech + wanghan_verified + asr_quality_pass + hallucination_clear",
                "human_text_review_required": True,
            },
        },
    }

