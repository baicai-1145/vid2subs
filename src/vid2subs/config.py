from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Optional


@dataclass
class Vid2SubsConfig:
    """
    核心配置对象（阶段 1/2 最小版本）。

    后续阶段会逐步扩展字段，但保持向后兼容。
    """

    input_path: Path
    output_audio_path: Optional[Path] = None
    use_vocal_separation: bool = True
    source_lang: str = "EU"
    asr_backend: str = "auto"
    # 全局设备控制：None 表示自动（优先 GPU，否则 CPU），"cpu"/"cuda" 表示强制
    device: str | None = None
    output_srt_path: Optional[Path] = None
    output_srt_source_path: Optional[Path] = None
    output_srt_translated_path: Optional[Path] = None
    output_srt_bilingual_path: Optional[Path] = None
    max_silence: float = 1.0
    max_chars_per_sentence: int = 80
    translate_lang: Optional[str] = None
    translation_engine: str = "google"
    bilingual: bool = False
    translated_only: bool = False

    @classmethod
    def from_paths(
        cls,
        input_path: str | Path,
        output_audio_path: Optional[str | Path] = None,
        use_vocal_separation: bool = True,
        source_lang: str = "EU",
        asr_backend: str = "auto",
        device: str | None = None,
        output_srt_path: Optional[str | Path] = None,
        output_srt_source_path: Optional[str | Path] = None,
        output_srt_translated_path: Optional[str | Path] = None,
        output_srt_bilingual_path: Optional[str | Path] = None,
        max_silence: float = 1.0,
        max_chars_per_sentence: int | None = None,
        translate_lang: Optional[str] = None,
        translation_engine: str = "google",
        bilingual: bool = False,
        translated_only: bool = False,
    ) -> "Vid2SubsConfig":
        input_path_obj = Path(input_path).expanduser().resolve()
        if output_audio_path is not None:
            output_path_obj = Path(output_audio_path).expanduser().resolve()
        else:
            default_name = f"{input_path_obj.stem}_vocals_16k.wav"
            output_path_obj = input_path_obj.with_name(default_name)
        if output_srt_path is not None:
            output_srt_obj = Path(output_srt_path).expanduser().resolve()
        else:
            output_srt_obj = input_path_obj.with_suffix(".srt")

        output_srt_source_obj: Optional[Path]
        output_srt_translated_obj: Optional[Path]
        output_srt_bilingual_obj: Optional[Path]

        # 如果传入的是显式路径则直接使用，否则如果为 True 则基于主 SRT 路径自动生成
        base = output_srt_obj

        if isinstance(output_srt_source_path, (str, Path)):
            output_srt_source_obj = Path(output_srt_source_path).expanduser().resolve()
        elif output_srt_source_path:
            output_srt_source_obj = base.with_name(base.stem + ".source.srt")
        else:
            output_srt_source_obj = None

        if isinstance(output_srt_translated_path, (str, Path)):
            output_srt_translated_obj = Path(output_srt_translated_path).expanduser().resolve()
        elif output_srt_translated_path:
            output_srt_translated_obj = base.with_name(base.stem + ".translated.srt")
        else:
            output_srt_translated_obj = None

        if isinstance(output_srt_bilingual_path, (str, Path)):
            output_srt_bilingual_obj = Path(output_srt_bilingual_path).expanduser().resolve()
        elif output_srt_bilingual_path:
            output_srt_bilingual_obj = base.with_name(base.stem + ".bilingual.srt")
        else:
            output_srt_bilingual_obj = None

        # 统一设备控制：优先使用显式传入的 device，其次读取环境变量 VID2SUBS_DEVICE
        if device is None:
            env_dev = os.getenv("VID2SUBS_DEVICE", "").strip().lower()
            if env_dev in {"cpu", "cuda"}:
                device_value: str | None = env_dev
            elif env_dev in {"", "auto"}:
                device_value = None
            else:
                device_value = env_dev or None
        else:
            device_value = device

        # 从环境变量中读取默认的 max_chars_per_sentence（如果未显式传入）
        if max_chars_per_sentence is None:
            env_value = os.getenv("VID2SUBS_MAX_CHARS_PER_SENTENCE", "80")
            try:
                max_chars_per_sentence_value = int(env_value)
            except ValueError:
                max_chars_per_sentence_value = 80
        else:
            max_chars_per_sentence_value = max_chars_per_sentence

        return cls(
            input_path=input_path_obj,
            output_audio_path=output_path_obj,
            use_vocal_separation=use_vocal_separation,
            source_lang=source_lang,
            asr_backend=asr_backend,
            device=device_value,
            output_srt_path=output_srt_obj,
            output_srt_source_path=output_srt_source_obj,
            output_srt_translated_path=output_srt_translated_obj,
            output_srt_bilingual_path=output_srt_bilingual_obj,
            max_silence=max_silence,
            max_chars_per_sentence=max_chars_per_sentence_value,
            translate_lang=translate_lang,
            translation_engine=translation_engine,
            bilingual=bilingual,
            translated_only=translated_only,
        )
