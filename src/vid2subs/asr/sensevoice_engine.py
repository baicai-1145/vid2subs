from __future__ import annotations

from pathlib import Path
from typing import List
import re

from funasr import AutoModel  # type: ignore[import]

from .base import ASREngine
from .types import Word


class SenseVoiceASREngine(ASREngine):
    """
    基于 FunASR SenseVoiceSmall 的 ASR 引擎。

    参考 `sensevoice_asr_to_json.py`，优先从 `chunks` 或
    `timestamp` + `words` 中抽取时间戳。
    """

    def __init__(
        self,
        model_name: str = "iic/SenseVoiceSmall",
        device: str | None = None,
    ) -> None:
        # FunASR AutoModel 通常使用 "cuda:0" 或 "cpu" 形式的 device
        if device is None or device == "auto":
            actual_device: str | None = None
        elif device == "cuda":
            actual_device = "cuda:0"
        else:
            actual_device = device

        self.model = AutoModel(
            model=model_name,
            vad_model="fsmn-vad",
            vad_kwargs={
                "max_single_segment_time": 30000,
            },
            # 不再使用独立的 ct-punc 模型，改用 use_itn=True 让模型自带正规化+标点
            punc_model=None,
            punc_kwargs={},
            trust_remote_code=True,
            device=actual_device,
            disable_update=True,
        )

    @staticmethod
    def _clean_tags(text: str) -> str:
        """
        清理掉 <|en|> 这类标签，兼容中间被加空格的情况：
        例如 \"< | en | >\" 也能去掉。
        实现同 sensevoice_asr_to_json.py 中的 clean_tags 保持一致。
        """
        if not text:
            return ""
        # 去掉类似 <|xxx|> 或 < | xxx | >
        text = re.sub(r"<\s*\|\s*[^|>]*\s*\|\s*>", "", text)
        # 再把多余空格收一下
        return " ".join(text.split()).strip()

    def _run_asr_raw(self, audio_path: str) -> dict:
        res = self.model.generate(
            input=audio_path,
            merge_vad=True,
            output_timestamp=True,
            batch_size_s=60,
            # 使用 use_itn=True 让模型输出自带标点和正规化文本
            use_itn=True,
            language="auto",
        )
        if isinstance(res, list) and res:
            return res[0]
        return res

    def _normalize_result(self, asr_result: dict, audio_path: str) -> dict:
        raw_text = asr_result.get("text") or ""
        text = self._clean_tags(raw_text)
        segments: list[dict] = []

        raw_chunks = asr_result.get("chunks") or []
        if raw_chunks:
            for ch in raw_chunks:
                seg_raw = ch.get("text") or ""
                seg_text = self._clean_tags(seg_raw)
                ts = ch.get("timestamp", [None, None])
                start, end = None, None
                if isinstance(ts, (list, tuple)) and len(ts) >= 2:
                    start, end = ts[0], ts[1]
                segments.append(
                    {
                        "text": seg_text,
                        "start": float(start) if start is not None else None,
                        "end": float(end) if end is not None else None,
                    }
                )
        elif "timestamp" in asr_result and "words" in asr_result:
            ts_list = asr_result.get("timestamp") or []
            words = asr_result.get("words") or []
            for st_ed, w in zip(ts_list, words):
                if not isinstance(st_ed, (list, tuple)) or len(st_ed) < 2:
                    continue
                st_ms, ed_ms = st_ed[0], st_ed[1]
                start = float(st_ms) / 1000.0
                end = float(ed_ms) / 1000.0
                segments.append(
                    {
                        "text": self._clean_tags(w or ""),
                        "start": start,
                        "end": end,
                    }
                )

        return {
            "audio_path": audio_path,
            "text": text,
            "segments": segments,
            "raw": asr_result,
        }

    def transcribe(self, wav_path: str | Path, with_word_ts: bool = True) -> List[Word]:
        audio_path = str(Path(wav_path).expanduser().resolve())
        raw_result = self._run_asr_raw(audio_path)
        norm = self._normalize_result(raw_result, audio_path)

        words: List[Word] = []
        segments = norm.get("segments") or []
        if with_word_ts and segments:
            for seg in segments:
                text = (seg.get("text") or "").strip()
                start = seg.get("start")
                end = seg.get("end")
                if not text:
                    continue
                if start is None or end is None:
                    start = 0.0
                    end = 0.0
                words.append(Word(text=text, start=float(start), end=float(end)))
        else:
            text = (norm.get("text") or "").strip()
            if text:
                words.append(Word(text=text, start=0.0, end=0.0))
        return words
