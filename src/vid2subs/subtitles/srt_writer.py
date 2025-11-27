from __future__ import annotations

from pathlib import Path
from typing import Iterable, List

from vid2subs.segmentation import Sentence

from .types import SubtitleItem


def _format_timestamp(seconds: float) -> str:
    if seconds < 0:
        seconds = 0.0
    total_ms = int(round(seconds * 1000))
    ms = total_ms % 1000
    total_seconds = total_ms // 1000
    s = total_seconds % 60
    total_minutes = total_seconds // 60
    m = total_minutes % 60
    h = total_minutes // 60
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def sentences_to_subtitle_items(sentences: Iterable[Sentence]) -> List[SubtitleItem]:
    items: List[SubtitleItem] = []
    for idx, sent in enumerate(sentences, start=1):
        text = sent.text.strip()
        if not text:
            continue
        items.append(
            SubtitleItem(
                index=idx,
                start=sent.start,
                end=sent.end,
                text=text,
            )
        )
    return items


def subtitle_items_to_srt(
    items: Iterable[SubtitleItem],
    bilingual: bool = False,
    translated_only: bool = False,
) -> str:
    lines: list[str] = []
    for item in items:
        start_ts = _format_timestamp(item.start)
        end_ts = _format_timestamp(item.end)
        text = item.text
        translation = item.translation if item.translation else None
        lines.append(str(item.index))
        lines.append(f"{start_ts} --> {end_ts}")
        if translated_only:
            # 仅输出译文；如果译文为空，则保留原文以避免空行
            lines.append(translation if translation is not None else text)
        elif bilingual and translation:
            lines.append(text)
            lines.append(translation)
        else:
            lines.append(text)
        lines.append("")  # 空行分隔
    return "\n".join(lines).strip() + "\n"


def write_srt(
    items: Iterable[SubtitleItem],
    path: str | Path,
    bilingual: bool = False,
    translated_only: bool = False,
) -> Path:
    srt_text = subtitle_items_to_srt(
        items,
        bilingual=bilingual,
        translated_only=translated_only,
    )
    out_path = Path(path).expanduser().resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(srt_text, encoding="utf-8")
    return out_path
