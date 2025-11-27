from __future__ import annotations

from vid2subs.subtitles import SubtitleItem

from .google_translator import GoogleTranslator
from .llm_translator import LLMTranslator
from .m2m_translator import M2M100Translator
from .translator import TranslationEngine


def get_translation_engine(name: str, device: str | None = None) -> TranslationEngine:
    """
    根据名称返回对应的翻译引擎实例。

    支持：
      - "google" : GoogleTranslator
      - "m2m100" : M2M100Translator
      - "llm"    : LLMTranslator
    """
    key = name.lower()
    if key == "google":
        return GoogleTranslator()
    if key == "m2m100":
        return M2M100Translator(device=device)
    if key == "llm":
        return LLMTranslator()
    raise ValueError(f"Unknown translation engine: {name}")
