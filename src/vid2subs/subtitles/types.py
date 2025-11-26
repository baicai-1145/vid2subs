from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SubtitleItem:
    """
    单条字幕项，对应 SRT 中的一行时间轴块。
    """

    index: int
    start: float
    end: float
    text: str
    translation: str | None = None

