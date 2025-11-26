from __future__ import annotations

from dataclasses import dataclass
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
    output_srt_path: Optional[Path] = None
    max_silence: float = 1.0
    max_chars_per_sentence: int = 80
    translate_lang: Optional[str] = None
    translation_engine: str = "google"
    bilingual: bool = False

    @classmethod
    def from_paths(
        cls,
        input_path: str | Path,
        output_audio_path: Optional[str | Path] = None,
        use_vocal_separation: bool = True,
        source_lang: str = "EU",
        asr_backend: str = "auto",
        output_srt_path: Optional[str | Path] = None,
        max_silence: float = 1.0,
        max_chars_per_sentence: int = 80,
        translate_lang: Optional[str] = None,
        translation_engine: str = "google",
        bilingual: bool = False,
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
        return cls(
            input_path=input_path_obj,
            output_audio_path=output_path_obj,
            use_vocal_separation=use_vocal_separation,
            source_lang=source_lang,
            asr_backend=asr_backend,
            output_srt_path=output_srt_obj,
            max_silence=max_silence,
            max_chars_per_sentence=max_chars_per_sentence,
            translate_lang=translate_lang,
            translation_engine=translation_engine,
            bilingual=bilingual,
        )
