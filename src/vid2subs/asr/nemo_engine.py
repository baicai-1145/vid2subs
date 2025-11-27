from __future__ import annotations

import time
from pathlib import Path
from typing import List, Tuple

import torch
import torchaudio
from nemoasr2pytorch.asr.api import (  # type: ignore[import]
    load_default_parakeet_tdt_model,
    load_parakeet_tdt_bf16,
    load_parakeet_tdt_fp16,
    transcribe,
    transcribe_amp,
)
from nemoasr2pytorch.vad.api import (  # type: ignore[import]
    load_default_frame_vad_model,
    run_vad_on_waveform,
)

from .base import ASREngine
from .types import Word


MODEL_MAX_SEC = {
    "EN": 24 * 60.0,
    "EU": 3 * 60.0 * 60.0,
}


def _load_waveform_mono(path: Path, target_sr: int) -> torch.Tensor:
    if not path.is_file():
        raise FileNotFoundError(f"音频文件不存在: {path}")
    sig, sr = torchaudio.load(str(path))
    if sig.size(0) > 1:
        sig = sig.mean(dim=0, keepdim=True)
    sig = sig.squeeze(0)
    if sr != target_sr:
        sig = torchaudio.functional.resample(sig, orig_freq=sr, new_freq=target_sr)
    return sig.float()


def _group_vad_segments(segments, min_seg: float, max_seg: float) -> List[Tuple[float, float]]:
    if not segments:
        return []

    groups: List[Tuple[float, float]] = []
    cur_start = float(segments[0].start)
    cur_end = float(segments[0].end)
    for seg in segments[1:]:
        s = float(seg.start)
        e = float(seg.end)
        if e - cur_start <= max_seg:
            cur_end = e
        else:
            groups.append((cur_start, cur_end))
            cur_start, cur_end = s, e
    groups.append((cur_start, cur_end))

    merged: List[Tuple[float, float]] = []
    for g in groups:
        if not merged:
            merged.append(g)
            continue
        prev_start, prev_end = merged[-1]
        prev_len = prev_end - prev_start
        if prev_len < min_seg:
            merged[-1] = (prev_start, g[1])
        else:
            merged.append(g)
    return merged


def _split_without_vad(duration_sec: float, max_seg: float) -> List[Tuple[float, float]]:
    segments: List[Tuple[float, float]] = []
    start = 0.0
    while start < duration_sec:
        end = min(start + max_seg, duration_sec)
        segments.append((start, end))
        start = end
    return segments


class NemoASREngine(ASREngine):
    """
    基于 Parakeet-TDT 的长语音 ASR 引擎，封装自 Example/nemo_inference.py。
    """

    def __init__(
        self,
        lang: str = "EU",
        precision: str = "fp32",
        cpu_only: bool = False,
        device: str | None = None,
        use_vad: bool = True,
        min_seg: float = 10.0,
        max_seg: float = 60.0,
        vad_threshold: float = 0.5,
    ) -> None:
        self.lang = lang.upper()
        if self.lang not in MODEL_MAX_SEC:
            raise ValueError(f"不支持的 NEMO 语言预设: {lang}")

        self.device = device

        if cpu_only and precision != "fp32":
            precision = "fp32"
        self.precision = precision
        self.cpu_only = cpu_only
        self.use_vad = use_vad
        self.min_seg = min_seg
        self.max_seg = max_seg
        self.vad_threshold = vad_threshold

        self._model = None
        self._target_sr: int | None = None

    def _ensure_model(self) -> None:
        if self._model is not None:
            return
        # 优先使用显式指定的 device，否则根据 cpu_only 选择
        device_override: str | None = self.device
        if device_override is None and self.cpu_only:
            device_override = "cpu"
        t_start = time.perf_counter()
        if self.precision == "fp32":
            asr_model = load_default_parakeet_tdt_model(lang=self.lang, device=device_override)
            asr_infer = transcribe
        elif self.precision == "fp16":
            asr_model = load_parakeet_tdt_fp16(device=device_override, lang=self.lang)
            asr_infer = transcribe_amp
        else:
            asr_model = load_parakeet_tdt_bf16(device=device_override, lang=self.lang)
            asr_infer = transcribe_amp
        self._model = (asr_model, asr_infer)
        self._target_sr = asr_model.sample_rate
        _ = time.perf_counter() - t_start

    def transcribe(self, wav_path: str | Path, with_word_ts: bool = True) -> List[Word]:
        self._ensure_model()
        assert self._model is not None
        assert self._target_sr is not None
        asr_model, asr_infer = self._model
        target_sr = self._target_sr

        audio_path = Path(wav_path).expanduser().resolve()
        waveform = _load_waveform_mono(audio_path, target_sr=target_sr)
        total_duration = waveform.numel() / float(target_sr)

        max_model_sec = MODEL_MAX_SEC[self.lang]
        effective_max_seg = min(self.max_seg, max_model_sec)

        if self.use_vad:
            # VAD 目前仍默认在 CPU 上运行，避免与 ASR 设备冲突
            vad_model = load_default_frame_vad_model(device="cpu")
            vad_sr = vad_model.preprocessor.sample_rate
            if vad_sr != target_sr:
                raise RuntimeError(
                    f"VAD sample_rate={vad_sr} 与 ASR sample_rate={target_sr} 不一致，当前实现假定两者相同。"
                )
            _, vad_segments = run_vad_on_waveform(
                vad_model,
                waveform,
                threshold=self.vad_threshold,
            )
            del vad_model
            if torch.cuda.is_available() and not self.cpu_only:
                torch.cuda.empty_cache()
            if not vad_segments:
                return []
            segments_sec = _group_vad_segments(
                vad_segments,
                min_seg=self.min_seg,
                max_seg=effective_max_seg,
            )
        else:
            segments_sec = _split_without_vad(total_duration, effective_max_seg)

        words: List[Word] = []
        asr_device = next(asr_model.parameters()).device
        for start_s, end_s in segments_sec:
            start_idx = int(round(start_s * target_sr))
            end_idx = int(round(end_s * target_sr))
            chunk = waveform[start_idx:end_idx]
            if chunk.numel() == 0:
                continue
            if with_word_ts and hasattr(asr_model, "transcribe_with_word_timestamps"):
                text, word_offsets = asr_model.transcribe_with_word_timestamps(  # type: ignore[attr-defined]
                    chunk.to(device=asr_device)
                )
                if word_offsets:
                    for w in word_offsets:
                        w_start = float(w["start"]) + start_s
                        w_end = float(w["end"]) + start_s
                        words.append(Word(text=w["word"], start=w_start, end=w_end))
            else:
                text = asr_infer(asr_model, chunk)
                text = text.strip()
                if not text:
                    continue
                words.append(Word(text=text, start=start_s, end=end_s))
        return words
