from __future__ import annotations

from pathlib import Path
from typing import Iterable

from .types import SubtitleItem


def _format_ass_timestamp(seconds: float) -> str:
    """
    将秒数转换为 ASS 时间戳格式：H:MM:SS.cc
    """
    if seconds < 0:
        seconds = 0.0
    total_cs = int(round(seconds * 100))  # centiseconds
    cs = total_cs % 100
    total_seconds = total_cs // 100
    s = total_seconds % 60
    total_minutes = total_seconds // 60
    m = total_minutes % 60
    h = total_minutes // 60
    return f"{h:d}:{m:02d}:{s:02d}.{cs:02d}"


def subtitle_items_to_ass(
    items: Iterable[SubtitleItem],
    bilingual: bool = False,
    translated_only: bool = False,
    play_res_x: int = 1920,
    play_res_y: int = 1080,
) -> str:
    """
    将 SubtitleItem 列表转换为一个简单的 ASS 字幕文本。

    设计目标：
      - 使用单一 Default 样式；
      - 文本内容与 SRT 逻辑保持一致（支持 bilingual / translated_only）。
    """
    header_lines: list[str] = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {play_res_x}",
        f"PlayResY: {play_res_y}",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
        "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding",
        # 黑底白字，底部居中，对应 Alignment=2
        "Style: Default,Arial,48,&H00FFFFFF,&H000000FF,&H00000000,&H64000000,"
        "0,0,0,0,100,100,0,0,1,2,0,2,10,10,30,1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]

    event_lines: list[str] = []
    for item in items:
        start_ts = _format_ass_timestamp(item.start)
        end_ts = _format_ass_timestamp(item.end)
        text = item.text or ""
        translation = item.translation if item.translation else None

        if translated_only:
            display = translation if translation is not None else text
        elif bilingual and translation:
            display = f"{text}\\N{translation}"
        else:
            display = text

        if not display.strip():
            continue

        # ASS 中需要对特殊字符进行转义
        safe_text = (
            display.replace("\\", r"\\")
            .replace("{", r"\{")
            .replace("}", r"\}")
        )
        event_lines.append(
            f"Dialogue: 0,{start_ts},{end_ts},Default,,0,0,0,,{safe_text}"
        )

    lines = header_lines + event_lines
    return "\n".join(lines) + "\n"


def write_ass(
    items: Iterable[SubtitleItem],
    path: str | Path,
    bilingual: bool = False,
    translated_only: bool = False,
) -> Path:
    ass_text = subtitle_items_to_ass(
        items,
        bilingual=bilingual,
        translated_only=translated_only,
    )
    out_path = Path(path).expanduser().resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(ass_text, encoding="utf-8")
    return out_path

