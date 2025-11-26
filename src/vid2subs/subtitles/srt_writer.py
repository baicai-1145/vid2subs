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


def subtitle_items_to_srt(items: Iterable[SubtitleItem], bilingual: bool = False) -> str:
    lines: list[str] = []
    for item in items:
        start_ts = _format_timestamp(item.start)
        end_ts = _format_timestamp(item.end)
        lines.append(str(item.index))
        lines.append(f"{start_ts} --> {end_ts}")
        if bilingual and item.translation:
            lines.append(item.text)
            lines.append(item.translation)
        else:
            lines.append(item.text)
        lines.append("")  # 空行分隔
    return "\n".join(lines).strip() + "\n"


def write_srt(
    items: Iterable[SubtitleItem],
    path: str | Path,
    bilingual: bool = False,
) -> Path:
    srt_text = subtitle_items_to_srt(items, bilingual=bilingual)
    out_path = Path(path).expanduser().resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(srt_text, encoding="utf-8")
    return out_path

