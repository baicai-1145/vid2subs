from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .env import load_dotenv_if_present
from .config import Vid2SubsConfig
from .pipeline import Vid2SubsPipeline


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="vid2subs",
        description="vid2subs: 从视频/音频生成字幕，可选人声提取、ASR 与翻译。",
    )
    parser.add_argument(
        "input",
        type=str,
        help="输入视频或音频文件路径。",
    )
    parser.add_argument(
        "--lang",
        type=str,
        default="EU",
        help="源语言代码：EN / EU / 其它（默认为 SenseVoiceSmall）。",
    )
    parser.add_argument(
        "--asr-backend",
        type=str,
        choices=["auto", "nemo", "sensevoice"],
        default="auto",
        help="ASR 后端选择：auto / nemo / sensevoice。",
    )
    parser.add_argument(
        "--output-wav",
        type=str,
        default=None,
        help="输出 16kHz 单声道 WAV 文件路径（默认: 与输入同目录，文件名加 _vocals_16k 后缀）。",
    )
    parser.add_argument(
        "--no-vocal-sep",
        action="store_true",
        help="不做人声分离，仅直接提取并重采样音频。",
    )
    parser.add_argument(
        "--output-srt",
        type=str,
        default=None,
        help="如果指定，将在完成 ASR 后输出 SRT 字幕文件（默认路径: 与输入同名 .srt）。",
    )
    parser.add_argument(
        "--max-silence",
        type=float,
        default=1.0,
        help="句子切分时允许的最大静音间隔（秒，默认: 1.0）。",
    )
    parser.add_argument(
        "--max-chars-per-sentence",
        type=int,
        default=80,
        help="单句最大字符数（超过后尝试断句，默认: 80）。",
    )
    parser.add_argument(
        "--translate",
        type=str,
        default=None,
        help="目标翻译语言代码（如: zh, en）。设置后会为字幕生成译文。",
    )
    parser.add_argument(
        "--translation-engine",
        type=str,
        choices=["google", "m2m100", "llm"],
        default="google",
        help="翻译引擎选择：google / m2m100 / llm。",
    )
    parser.add_argument(
        "--bilingual",
        action="store_true",
        help="在 SRT 中输出双语字幕（原文 + 译文）。",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    # 确保在解析参数和使用配置之前加载 .env 中的环境变量
    load_dotenv_if_present()
    if argv is None:
        argv = sys.argv[1:]

    parser = build_arg_parser()
    args = parser.parse_args(argv)

    input_path = args.input
    output_wav = args.output_wav
    output_srt = args.output_srt
    source_lang = args.lang
    asr_backend = args.asr_backend
    use_vocal_separation = not args.no_vocal_sep
    translate_lang = args.translate
    translation_engine = args.translation_engine
    bilingual = args.bilingual

    try:
        config = Vid2SubsConfig.from_paths(
            input_path=input_path,
            output_audio_path=output_wav,
            use_vocal_separation=use_vocal_separation,
            source_lang=source_lang,
            asr_backend=asr_backend,
            output_srt_path=output_srt,
            max_silence=args.max_silence,
            max_chars_per_sentence=args.max_chars_per_sentence,
             translate_lang=translate_lang,
             translation_engine=translation_engine,
             bilingual=bilingual,
        )
        pipeline = Vid2SubsPipeline(config)
        # 若指定了输出 SRT 或翻译，则执行完整字幕流程
        if output_srt or translate_lang:
            items = pipeline.run_to_subtitles()
            print("字幕生成完成")
            print(f"   输入: {Path(input_path)}")
            print(f"   音频: {config.output_audio_path}")
            if config.output_srt_path:
                print(f"   字幕: {config.output_srt_path}")
            print(f"   条目数: {len(items)}")
        else:
            output_path = pipeline.run_audio_extraction()
            print("音频提取完成")
            print(f"   输入: {Path(input_path)}")
            print(f"   输出: {output_path}")
        return 0
    except KeyboardInterrupt:
        print("\n用户中断")
        return 1
    except Exception as exc:
        print(f"处理失败: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
