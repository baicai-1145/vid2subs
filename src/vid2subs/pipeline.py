from __future__ import annotations

from pathlib import Path
from typing import List
import os

from .config import Vid2SubsConfig
from .audio.extractor import extract_audio
from .asr import Word, get_asr_engine
from .segmentation import Sentence, words_to_sentences
from .subtitles import SubtitleItem, sentences_to_subtitle_items, write_srt
from .translate.factory import get_translation_engine
from .langdetect import detect_lang_code


class Vid2SubsPipeline:
    """
    项目主 Pipeline 的最小实现。

    当前阶段仅负责音频/人声提取，后续会逐步扩展到
    ASR、分句、字幕生成与翻译。
    """

    def __init__(self, config: Vid2SubsConfig) -> None:
        self.config = config

    def run_audio_extraction(self) -> Path:
        if self.config.output_audio_path is None:
            raise ValueError("output_audio_path 未在配置中设置")
        return extract_audio(
            input_path=self.config.input_path,
            output_path=self.config.output_audio_path,
            use_vocal_separation=self.config.use_vocal_separation,
        )

    def run_asr(self, audio_path: Path | None = None) -> List[Word]:
        """
        对 16kHz 单声道 WAV 进行 ASR，返回词级时间戳。
        """
        if audio_path is None:
            if self.config.output_audio_path is None:
                raise ValueError("未提供音频路径，且配置中缺少 output_audio_path")
            audio_path = self.config.output_audio_path
        engine = get_asr_engine(
            lang=self.config.source_lang,
            backend=self.config.asr_backend,  # type: ignore[arg-type]
            device=self.config.device,
        )
        return engine.transcribe(audio_path)

    def run_segmentation(self, words: List[Word]) -> List[Sentence]:
        return words_to_sentences(
            words,
            max_silence=self.config.max_silence,
            max_chars=self.config.max_chars_per_sentence,
        )

    def run_to_subtitles(self) -> List[SubtitleItem]:
        """
        从输入文件一路执行到字幕列表，并在配置指定时写出 SRT 文件。
        """
        audio_path = self.run_audio_extraction()
        words = self.run_asr(audio_path)
        sentences = self.run_segmentation(words)
        items = sentences_to_subtitle_items(sentences)

        # 可选翻译阶段
        if self.config.translate_lang:
            engine = get_translation_engine(self.config.translation_engine, device=self.config.device)
            engine_name = self.config.translation_engine.lower()
            translations: list[str]

            if engine_name in {"llm", "google"}:
                # LLM / Google 翻译都可以使用自动源语言检测
                source_lang_for_translation = "auto"
                translations = engine.translate_subtitles(
                    items,
                    source_lang=source_lang_for_translation,
                    target_lang=self.config.translate_lang,
                )
            elif engine_name == "m2m100" and self.config.source_lang.upper() in {"EU", "AUTO"}:
                # 多语言 ASR 场景（如 Nemo EU / SenseVoice），为 M2M100 检测每条字幕的源语言，
                # 然后按语言分组批量翻译，避免逐条调用导致的性能问题。
                translations = ["" for _ in items]
                last_lang: str = "en"
                lang_stats: dict[str, int] = {}
                lang_to_indices: dict[str, list[int]] = {}

                for idx, item in enumerate(items):
                    text = item.text or ""
                    detected = detect_lang_code(text)
                    if detected:
                        last_lang = detected
                    src_lang = last_lang
                    lang_stats[src_lang] = lang_stats.get(src_lang, 0) + 1
                    lang_to_indices.setdefault(src_lang, []).append(idx)

                for src_lang, indices in lang_to_indices.items():
                    batch_items = [items[i] for i in indices]
                    batch_translations = engine.translate_subtitles(
                        batch_items,
                        source_lang=src_lang,
                        target_lang=self.config.translate_lang,
                    )
                    for i, t in zip(indices, batch_translations):
                        translations[i] = t

                if lang_stats:
                    print("\n[LangDetect] M2M100 源语言检测统计：")
                    for code, count in sorted(lang_stats.items(), key=lambda kv: kv[1], reverse=True):
                        print(f"  {code}: {count} 条字幕")
            else:
                # 固定源语言场景：统一使用 config.source_lang
                translations = engine.translate_subtitles(
                    items,
                    source_lang=self.config.source_lang,
                    target_lang=self.config.translate_lang,
                )

            for item, translated_text in zip(items, translations):
                item.translation = translated_text

        # 默认输出（兼容原有行为）
        if self.config.output_srt_path is not None:
            write_srt(
                items,
                self.config.output_srt_path,
                bilingual=self.config.bilingual,
                translated_only=self.config.translated_only,
            )

        # 若配置了额外输出，则分别写入对应文件
        if self.config.output_srt_source_path is not None:
            write_srt(
                items,
                self.config.output_srt_source_path,
                bilingual=False,
                translated_only=False,
            )
        if self.config.output_srt_translated_path is not None:
            write_srt(
                items,
                self.config.output_srt_translated_path,
                bilingual=False,
                translated_only=True,
            )
        if self.config.output_srt_bilingual_path is not None:
            write_srt(
                items,
                self.config.output_srt_bilingual_path,
                bilingual=True,
                translated_only=False,
            )
        return items
