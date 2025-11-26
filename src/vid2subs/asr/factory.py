from __future__ import annotations

from typing import Literal

from .base import ASREngine
from .nemo_engine import NemoASREngine
from .sensevoice_engine import SenseVoiceASREngine


BackendType = Literal["auto", "nemo", "sensevoice"]


def get_asr_engine(
    lang: str,
    backend: BackendType = "auto",
) -> ASREngine:
    """
    根据语言和后端选择合适的 ASR 引擎。

    - EN/EU 优先使用 NEMO；
    - 其它语言默认使用 SenseVoiceSmall。
    """
    lang_upper = lang.upper()

    if backend == "nemo":
        return NemoASREngine(lang="EN" if lang_upper == "EN" else "EU")
    if backend == "sensevoice":
        return SenseVoiceASREngine()

    if lang_upper in {"EN", "EU"}:
        return NemoASREngine(lang=lang_upper)

    return SenseVoiceASREngine()

