from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Optional

import librosa
import soundfile as sf


def _get_cache_root() -> Path:
    custom_root = os.getenv("VID2SUBS_CACHE_DIR")
    if custom_root:
        return Path(custom_root).expanduser().resolve()
    return Path.home() / ".cache" / "vid2subs"


def _get_model_dir() -> Path:
    cache_root = _get_cache_root()
    model_dir = cache_root / "models" / "mel_band_roformer"
    model_dir.mkdir(parents=True, exist_ok=True)
    return model_dir


def _get_vocals_dir() -> Path:
    cache_root = _get_cache_root()
    vocals_dir = cache_root / "separation" / "vocals"
    vocals_dir.mkdir(parents=True, exist_ok=True)
    return vocals_dir


def _download_file(url: str, dest_path: Path, timeout: int = 60) -> None:
    import socket
    import urllib.request
    from urllib.error import URLError

    original_timeout = socket.getdefaulttimeout()
    try:
        socket.setdefaulttimeout(timeout)
        print(f"开始下载模型文件: {url}")
        urllib.request.urlretrieve(url, dest_path)
        print(f"模型下载完成: {dest_path}")
    except (URLError, socket.timeout) as download_error:
        raise RuntimeError(f"模型下载失败: {download_error}") from download_error
    finally:
        socket.setdefaulttimeout(original_timeout)


def _setup_pymss_separator() -> Optional["object"]:
    try:
        from pymss import MSSeparator, get_separation_logger  # type: ignore[import]
    except ImportError:
        print("未安装 pymss，将跳过人声分离，仅提取原始音频。")
        return None

    model_config = {
        "model_type": "mel_band_roformer",
        "model_url": "https://www.modelscope.cn/models/baicai1145/models/resolve/master/mel_band_roformer/kimmel_unwa_ft2_bleedless_infer_fp16.pt",
        "config_url": "https://www.modelscope.cn/models/baicai1145/models/resolve/master/mel_band_roformer/config_kimmel_unwa_ft.yaml",
    }

    model_dir = _get_model_dir()
    model_path = model_dir / "kimmel_unwa_ft2_bleedless_infer_fp16.pt"
    config_path = model_dir / "config_kimmel_unwa_ft.yaml"

    if not model_path.exists():
        _download_file(model_config["model_url"], model_path)
    if not config_path.exists():
        _download_file(model_config["config_url"], config_path)

    vocals_dir = _get_vocals_dir()

    device = "cpu"
    try:
        import torch  # type: ignore[import]

        if torch.cuda.is_available():
            device = "cuda"
            print("检测到 CUDA，将使用 GPU 进行人声分离")
        else:
            print("CUDA 不可用，将在 CPU 上进行人声分离")
    except ImportError:
        print("未安装 PyTorch，将在 CPU 上进行人声分离")

    try:
        separator = MSSeparator(
            model_type=model_config["model_type"],
            model_path=str(model_path),
            config_path=str(config_path),
            device=device,
            device_ids=[0],
            output_format="wav",
            use_tta=False,
            store_dirs={
                "vocals": str(vocals_dir),
                "other": None,
            },
            audio_params={
                "wav_bit_depth": "FLOAT",
            },
            logger=get_separation_logger(),
            debug=False,
            inference_params={
                "batch_size": 1,
                "num_overlap": 1,
                "chunk_size": 485100,
            },
        )
        print("pymss 分离器初始化完成")
        return separator
    except Exception as init_error:
        print(f"pymss 初始化失败，将跳过人声分离: {init_error}")
        return None


def _convert_to_16k_mono(input_file: Path, output_file: Path) -> Path:
    print(f"转换为 16kHz 单声道 WAV: {input_file}")
    audio, sample_rate = librosa.load(str(input_file), sr=16000, mono=True)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(output_file), audio, 16000, format="WAV", subtype="PCM_16")
    duration = len(audio) / 16000.0
    print(f"转换完成: {output_file} ({duration:.2f} 秒)")
    return output_file


def _extract_raw_audio(input_path: Path, output_file: Path) -> Path:
    print(f"从输入文件提取音频: {input_path}")
    audio, sample_rate = librosa.load(str(input_path), sr=None, mono=False)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    if audio.ndim > 1:
        sf.write(str(output_file), audio.T, sample_rate, format="WAV", subtype="PCM_16")
    else:
        sf.write(str(output_file), audio, sample_rate, format="WAV", subtype="PCM_16")
    if audio.ndim == 1:
        duration = len(audio) / float(sample_rate)
        channels = 1
    else:
        duration = len(audio[0]) / float(sample_rate)
        channels = audio.shape[0]
    print(
        f"音频提取完成: {output_file} "
        f"(采样率 {sample_rate} Hz, 声道数 {channels}, 时长 {duration:.2f} 秒)"
    )
    return output_file


def extract_audio(
    input_path: str | Path,
    use_vocal_separation: bool = True,
    output_path: Optional[str | Path] = None,
) -> Path:
    """
    提取输入视频/音频中的人声或整体音频，并统一转换为 16kHz 单声道 WAV。

    优先尝试使用 pymss 进行人声分离；如未安装或运行失败，则自动退回为
    直接音频提取与重采样。
    """
    input_path_obj = Path(input_path).expanduser().resolve()
    if not input_path_obj.exists():
        raise FileNotFoundError(f"输入文件不存在: {input_path_obj}")

    if output_path is not None:
        output_path_obj = Path(output_path).expanduser().resolve()
    else:
        default_name = f"{input_path_obj.stem}_vocals_16k.wav"
        output_path_obj = input_path_obj.with_name(default_name)

    if use_vocal_separation:
        separator = _setup_pymss_separator()
        if separator is not None:
            try:
                print("开始人声分离")
                with tempfile.TemporaryDirectory() as temp_dir:
                    temp_input_dir = Path(temp_dir) / "input"
                    temp_input_dir.mkdir(parents=True, exist_ok=True)
                    temp_audio_path = temp_input_dir / f"{input_path_obj.stem}.wav"
                    _extract_raw_audio(input_path_obj, temp_audio_path)
                    separator.process_folder(str(temp_input_dir))
                vocals_dir = _get_vocals_dir()
                candidate_files = list(
                    vocals_dir.glob(f"{input_path_obj.stem}*vocals*.wav")
                )
                if candidate_files:
                    candidate_files.sort(key=lambda path: path.stat().st_mtime)
                    vocal_file = candidate_files[-1]
                    print(f"人声分离完成: {vocal_file}")
                    return _convert_to_16k_mono(vocal_file, output_path_obj)
                print("未找到分离后的人声文件，将使用直接音频提取。")
            except Exception as separation_error:

                print(f"人声分离失败，将使用直接音频提取: {separation_error}")
    print("使用直接音频提取模式")
    return _convert_to_16k_mono(input_path_obj, output_path_obj)
