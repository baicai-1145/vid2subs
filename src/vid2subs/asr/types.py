from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Word:
    """
    词级时间戳结构，用于后续分句与字幕生成。
    """

    text: str
    start: float
    end: float

