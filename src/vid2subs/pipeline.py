from __future__ import annotations

from pathlib import Path
from typing import List

from .config import Vid2SubsConfig
from .audio.extractor import extract_audio
from .asr import Word, get_asr_engine
from .segmentation import Sentence, words_to_sentences
from .subtitles import SubtitleItem, sentences_to_subtitle_items, write_srt
from .translate.factory import get_translation_engine


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
            engine = get_translation_engine(self.config.translation_engine)
            translations = engine.translate_subtitles(
                items,
                source_lang=self.config.source_lang,
                target_lang=self.config.translate_lang,
            )
            for item, translated_text in zip(items, translations):
                item.translation = translated_text

        if self.config.output_srt_path is not None:
            write_srt(items, self.config.output_srt_path, bilingual=self.config.bilingual)
        return items
