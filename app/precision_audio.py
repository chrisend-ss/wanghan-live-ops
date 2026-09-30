from __future__ import annotations

import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import numpy as np


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
                avg_logprob = float(getattr(seg, "avg_logprob", 0.0) or 0.0)
                no_speech_prob = float(getattr(seg, "no_speech_prob", 0.0) or 0.0)

                # Conservative post-filter: precision mode prefers dropping
                # uncertain speech over hallucinating lyrics/noise as dialogue.
                if no_speech_prob >= 0.82 or avg_logprob < -1.35:
                    continue

                output.append(
                    {
                        "start_seconds": start,
                        "end_seconds": end,
                        "text": text,
                        "avg_logprob": avg_logprob,
                        "no_speech_prob": no_speech_prob,
                        "kind": "speech",
                    }
                )
    return output


def _load_mono_16k(path: Path):
    import soundfile as sf
    import torch

    samples, sample_rate = sf.read(str(path), dtype="float32", always_2d=False)
    if sample_rate != 16000:
        raise RuntimeError(f"Expected 16 kHz speaker clip, got {sample_rate}")
    if getattr(samples, "ndim", 1) > 1:
        samples = samples.mean(axis=1)
    return torch.from_numpy(np.asarray(samples, dtype=np.float32)).unsqueeze(0)


def _speaker_encoder():
    try:
        from speechbrain.inference.speaker import EncoderClassifier
    except ImportError as exc:
        raise RuntimeError("speechbrain is required for speaker clustering") from exc

    return EncoderClassifier.from_hparams(
        source="speechbrain/spkrec-ecapa-voxceleb",
        savedir="pretrained_models/spkrec-ecapa-voxceleb",
    )


def _embedding_for_range(
    encoder,
    audio_path: Path,
    start: float,
    end: float,
    temp: Path,
    name: str,
) -> Optional[np.ndarray]:
    if end - start < 0.75:
        return None

    clip = _extract_wav_range(audio_path, temp / f"{name}.wav", start, end)
    waveform = _load_mono_16k(clip)
    emb = encoder.encode_batch(waveform).detach().cpu().numpy().reshape(-1)
    norm = np.linalg.norm(emb)
    if norm <= 1e-9:
        return None
    return emb / norm


def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    denom = max(np.linalg.norm(a), 1e-9) * max(np.linalg.norm(b), 1e-9)
    return float(np.dot(a, b) / denom)


def assign_speakers(
    audio_path: Path,
    segments: List[Dict[str, Any]],
    *,
    wanghan_reference_ranges: Optional[Sequence[Sequence[float]]] = None,
    distance_threshold: float = 0.38,
) -> Dict[str, Any]:
    """Cluster speakers and identify WangHan conservatively.

    Best mode: provide clean WangHan-only time ranges from the same recording.
    Fallback mode: infer the anchor from dominance + early appearance and mark it
    medium confidence, never pretending that diarization is ground truth.
    """
    if not segments:
        return {"segments": segments, "speaker_summary": {}}

    from sklearn.cluster import AgglomerativeClustering

    encoder = _speaker_encoder()
    eligible: List[int] = []
    embeddings: List[np.ndarray] = []

    with tempfile.TemporaryDirectory(prefix="wanghan_speaker_") as temp_dir:
        temp = Path(temp_dir)

        for idx, seg in enumerate(segments):
            start = float(seg["start_seconds"])
            end = float(seg["end_seconds"])
            if end - start < 1.0:
                continue
            try:
                emb = _embedding_for_range(
                    encoder, audio_path, start, end, temp, f"seg_{idx:05d}"
                )
            except Exception:
                emb = None
            if emb is not None:
                eligible.append(idx)
                embeddings.append(emb)

        if not embeddings:
            for seg in segments:
                seg["speaker"] = "说话人_未知"
                seg["speaker_confidence"] = "low"
            return {
                "segments": segments,
                "speaker_summary": {"mode": "unavailable"},
            }

        matrix = np.vstack(embeddings)
        if len(matrix) == 1:
            labels = np.array([0], dtype=int)
        else:
            labels = AgglomerativeClustering(
                n_clusters=None,
                metric="cosine",
                linkage="average",
                distance_threshold=distance_threshold,
            ).fit_predict(matrix)

        cluster_embeddings: Dict[int, List[np.ndarray]] = {}
        cluster_duration: Dict[int, float] = {}
        cluster_first: Dict[int, float] = {}

        for seg_idx, emb, raw_label in zip(eligible, embeddings, labels):
            label = int(raw_label)
            seg = segments[seg_idx]
            cluster_embeddings.setdefault(label, []).append(emb)
            cluster_duration[label] = cluster_duration.get(label, 0.0) + max(
                0.0,
                float(seg["end_seconds"]) - float(seg["start_seconds"]),
            )
            cluster_first[label] = min(
                cluster_first.get(label, float("inf")),
                float(seg["start_seconds"]),
            )

        centroids: Dict[int, np.ndarray] = {}
        for label, embs in cluster_embeddings.items():
            centroid = np.mean(np.vstack(embs), axis=0)
            centroids[label] = centroid / max(np.linalg.norm(centroid), 1e-9)

        wanghan_cluster: Optional[int] = None
        identification_mode = "dominant_first"
        identification_score: Optional[float] = None

        refs: List[np.ndarray] = []
        for ref_idx, pair in enumerate(wanghan_reference_ranges or []):
            if len(pair) < 2:
                continue
            try:
                ref = _embedding_for_range(
                    encoder,
                    audio_path,
                    float(pair[0]),
                    float(pair[1]),
                    temp,
                    f"ref_{ref_idx:03d}",
                )
            except Exception:
                ref = None
            if ref is not None:
                refs.append(ref)

        if refs:
            reference = np.mean(np.vstack(refs), axis=0)
            reference = reference / max(np.linalg.norm(reference), 1e-9)
            scored = sorted(
                (
                    (label, _cosine_similarity(reference, centroid))
                    for label, centroid in centroids.items()
                ),
                key=lambda x: x[1],
                reverse=True,
            )
            if scored:
                wanghan_cluster, identification_score = scored[0]
                identification_mode = "same_recording_reference"
        else:
            total = max(sum(cluster_duration.values()), 1e-9)
            candidates = []
            for label in centroids:
                duration_share = cluster_duration[label] / total
                early_bonus = 1.0 / (1.0 + cluster_first[label] / 120.0)
                candidates.append(
                    (label, duration_share * 0.8 + early_bonus * 0.2)
                )
            candidates.sort(key=lambda x: x[1], reverse=True)
            if candidates:
                wanghan_cluster, identification_score = candidates[0]

        cluster_names: Dict[int, str] = {}
        other_counter = 1
        for label in sorted(centroids):
            if label == wanghan_cluster:
                cluster_names[label] = "王焓"
            else:
                cluster_names[label] = f"其他说话人_{other_counter}"
                other_counter += 1

        for seg_idx, raw_label in zip(eligible, labels):
            label = int(raw_label)
            segments[seg_idx]["speaker_cluster"] = label
            segments[seg_idx]["speaker"] = cluster_names[label]
            if label == wanghan_cluster and identification_mode == "same_recording_reference":
                segments[seg_idx]["speaker_confidence"] = (
                    "high" if (identification_score or 0.0) >= 0.65 else "medium"
                )
            else:
                segments[seg_idx]["speaker_confidence"] = "medium"

        eligible_set = set(eligible)
        for idx, seg in enumerate(segments):
            if idx in eligible_set:
                continue
            try:
                emb = _embedding_for_range(
                    encoder,
                    audio_path,
                    float(seg["start_seconds"]),
                    float(seg["end_seconds"]),
                    temp,
                    f"short_{idx:05d}",
                )
            except Exception:
                emb = None

            if emb is None:
                seg["speaker"] = "说话人_未知"
                seg["speaker_confidence"] = "low"
                continue

            scores = sorted(
                (
                    (label, _cosine_similarity(emb, centroid))
                    for label, centroid in centroids.items()
                ),
                key=lambda x: x[1],
                reverse=True,
            )
            best_label, best_score = scores[0]
            seg["speaker_cluster"] = int(best_label)
            seg["speaker"] = cluster_names[int(best_label)]
            seg["speaker_confidence"] = (
                "medium" if best_score >= 0.55 else "low"
            )

    summary = {
        "mode": identification_mode,
        "wanghan_cluster": (
            None if wanghan_cluster is None else int(wanghan_cluster)
        ),
        "identification_score": identification_score,
        "clusters": {
            str(label): {
                "name": cluster_names[label],
                "speech_seconds": round(cluster_duration.get(label, 0.0), 3),
                "first_seconds": round(cluster_first.get(label, 0.0), 3),
            }
            for label in sorted(cluster_names)
        },
    }
    return {"segments": segments, "speaker_summary": summary}


def build_precision_transcript(
    audio_path: Path,
    *,
    model_size: str = "large-v3",
    language: str = "zh",
    hotwords: Optional[str] = None,
    wanghan_reference_ranges: Optional[Sequence[Sequence[float]]] = None,
) -> Dict[str, Any]:
    zones = segment_speech_music(audio_path)
    speech_zones = merge_speech_zones(zones)

    speech_segments = transcribe_speech_zones(
        audio_path,
        speech_zones,
        model_size=model_size,
        language=language,
        hotwords=hotwords,
    )
    speaker_result = assign_speakers(
        audio_path,
        speech_segments,
        wanghan_reference_ranges=wanghan_reference_ranges,
    )
    speech_segments = speaker_result["segments"]

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
            "speech_segment_count": len(speech_segments),
            "zone_count": len(zones),
            "duration_by_zone_seconds": {
                k: round(v, 3) for k, v in durations.items()
            },
            "model": model_size,
            "music_is_not_transcribed": True,
            "singing_is_expected_to_be_labeled_music": True,
        },
    }
