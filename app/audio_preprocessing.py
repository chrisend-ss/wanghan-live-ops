"""Optional in-memory accompaniment isolation for speaker verification."""
from __future__ import annotations

from typing import Callable, Optional

import numpy as np


class VocalIsolation:
    def __init__(self, inference: Optional[Callable] = None):
        self._inference = inference
        self._model = None
        self.processed_count = 0
        self.failed_count = 0

    def _separate(self, samples: np.ndarray) -> np.ndarray:
        import torch
        import torchaudio

        bundle = torchaudio.pipelines.HDEMUCS_HIGH_MUSDB_PLUS
        if self._model is None:
            self._model = bundle.get_model().eval()
        wave = torch.from_numpy(samples.copy()).unsqueeze(0).repeat(2, 1)
        with torch.inference_mode():
            wave = torchaudio.functional.resample(wave, 16000, bundle.sample_rate)
            stems = self._model(wave.unsqueeze(0))
            vocals = stems[0, self._model.sources.index("vocals")].mean(0)
            vocals = torchaudio.functional.resample(vocals, bundle.sample_rate, 16000)
        return vocals.detach().cpu().numpy()[:len(samples)]

    def __call__(self, samples: np.ndarray) -> np.ndarray:
        try:
            source = np.asarray(samples, dtype=np.float32)
            if source.ndim != 1 or len(source) < 24000 or not np.isfinite(source).all():
                raise ValueError("Vocal isolation requires finite 16 kHz mono speech")
            result = np.asarray((self._inference or self._separate)(source.copy()), dtype=np.float32)
            if result.shape != source.shape or not np.isfinite(result).all():
                raise ValueError("Vocal isolation changed the timeline or returned invalid samples")
            rms = float(np.sqrt(np.mean(result.astype(np.float64) ** 2)))
            if rms < 1e-5:
                raise ValueError("Vocal isolation removed usable speech energy")
            self.processed_count += 1
            return result
        except Exception:
            self.failed_count += 1
            raise

    def summary(self):
        return {
            "method": "torchaudio_hdemucs_high_musdb_plus_vocals",
            "scope": "reference_and_candidate_speaker_windows",
            "sample_rate": 16000,
            "processed_window_count": self.processed_count,
            "failed_window_count": self.failed_count,
            "isolated_audio_persisted": False,
            "raw_fallback_on_failure": False,
            "limitation": "Vocals may retain song vocals or other speakers; separation can distort timbre",
        }
