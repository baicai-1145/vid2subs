from __future__ import annotations

from pathlib import Path
from typing import Optional


def load_dotenv_if_present(env_path: Optional[str | Path] = None) -> None:
    """
    尝试从项目根目录加载 .env 文件（如果存在）。

    - 不强制依赖 python-dotenv，若未安装则静默跳过；
    - 默认查找路径为 src/vid2subs/ 之上的仓库根目录下的 .env。
    """
    try:
        from dotenv import load_dotenv  # type: ignore[import]
    except ImportError:
        return

    if env_path is None:
        root = Path(__file__).resolve().parents[2]
        env_file = root / ".env"
    else:
        env_file = Path(env_path)

    if env_file.is_file():
        load_dotenv(dotenv_path=env_file, override=False)

