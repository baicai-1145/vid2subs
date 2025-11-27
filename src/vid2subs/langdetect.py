from __future__ import annotations

"""
简单的语言检测工具，用于在多语言场景下为 M2M100 选择合适的源语言代码。

当前实现基于 fast-langdetect，返回 fastText 语言代码（如 "en"、"zh"、"pt-br"）。
"""

from typing import Optional

from fast_langdetect import detect_language  # type: ignore[import]


def detect_lang_code(text: str, threshold: float = 0.80) -> Optional[str]:
    """
    使用 fast-langdetect 对给定文本进行语言检测。

    返回小写语言代码；如果文本为空或检测失败，则返回 None。
    fast-langdetect 本身会对输入长度进行处理，我们这里只做最小校验。
    """
    if not text or not text.strip():
        return None
    try:
        code = detect_language(text)
    except Exception:
        return None
    if not code:
        return None
    return code.lower()
