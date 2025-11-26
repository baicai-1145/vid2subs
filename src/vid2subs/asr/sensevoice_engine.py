from __future__ import annotations

from pathlib import Path
from typing import List

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
        self.model = AutoModel(
            model=model_name,
            vad_model="fsmn-vad",
            vad_kwargs={
                "max_single_segment_time": 30000,
            },
            punc_model="ct-punc",
            punc_kwargs={},
            trust_remote_code=True,
            device=device,
            disable_update=True,
        )

    def _run_asr_raw(self, audio_path: str) -> dict:
        res = self.model.generate(
            input=audio_path,
            merge_vad=True,
            output_timestamp=True,
            batch_size_s=60,
            do_punc=True,
            language="auto",
        )
        if isinstance(res, list) and res:
            return res[0]
        return res

    def _normalize_result(self, asr_result: dict, audio_path: str) -> dict:
        text = (asr_result.get("text") or "").strip()
        segments: list[dict] = []

        raw_chunks = asr_result.get("chunks") or []
        if raw_chunks:
            for ch in raw_chunks:
                seg_text = (ch.get("text") or "").strip()
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
                        "text": w,
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
