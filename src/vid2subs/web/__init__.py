from __future__ import annotations

"""
vid2subs Web 子模块

提供基于 FastAPI 的轻量 Web 界面与 API。
"""

from .app import app, create_app, main

__all__ = ["app", "create_app", "main"]

