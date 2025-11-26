from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import List

from .types import Word


class ASREngine(ABC):
    """
    抽象 ASR 引擎，封装不同后端（NEMO / SenseVoiceSmall）的统一接口。
    """

    @abstractmethod
    def transcribe(self, wav_path: str | Path, with_word_ts: bool = True) -> List[Word]:
        """
        对输入 WAV 文件进行转录，返回词级时间戳。
        """

