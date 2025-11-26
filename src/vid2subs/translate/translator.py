from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List

from vid2subs.subtitles import SubtitleItem


class TranslationEngine(ABC):
    """
    翻译引擎抽象接口。

    所有具体翻译实现（Google / M2M100 / LLM）都应遵循该接口，
    以便在 Pipeline 中进行统一调度。
    """

    @abstractmethod
    def translate_subtitles(
        self,
        items: List[SubtitleItem],
        source_lang: str,
        target_lang: str,
    ) -> List[str]:
        """
        将给定字幕项的 text 翻译为目标语言，返回与 items 一一对应的译文列表。
        """

