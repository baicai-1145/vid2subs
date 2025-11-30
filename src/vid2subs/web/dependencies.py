from __future__ import annotations

"""
Web 层与核心 Pipeline 之间的集成点。

当前仅提供若干高层封装函数，后续可在此扩展
Web 特有的行为（如临时目录管理、权限控制等）。
"""

from typing import List, Tuple, Dict, Any
from pathlib import Path
import os
import uuid
import shutil
import time
import json
from datetime import datetime

from vid2subs.config import Vid2SubsConfig
from vid2subs.pipeline import Vid2SubsPipeline
from vid2subs.subtitles import SubtitleItem


def run_pipeline_for_web(config: Vid2SubsConfig) -> List[SubtitleItem]:
    """
    Web 入口的高层封装。

    约定：
      - config.input_path 指向已在后端落地的音频/媒体文件；
      - 其它字段（语言、ASR 后端、翻译配置等）与 CLI 保持一致。

    当前实现直接复用 Vid2SubsPipeline.run_to_subtitles()。
    如未来 Web 版需要跳过人声分离或特殊处理，可在此集中调整。
    """
    pipeline = Vid2SubsPipeline(config)
    return pipeline.run_to_subtitles()


def get_web_jobs_root() -> Path:
    """
    获取 Web 任务工作目录根路径。

    默认使用当前工作目录下的 exports/web_jobs，可通过
    VID2SUBS_WEB_JOBS_DIR 环境变量覆盖。
    """
    root_env = os.getenv("VID2SUBS_WEB_JOBS_DIR")
    if root_env:
        root = Path(root_env).expanduser().resolve()
    else:
        root = Path.cwd() / "exports" / "web_jobs"
    root.mkdir(parents=True, exist_ok=True)
    return root


def create_job_dir() -> Tuple[str, Path]:
    """
    创建一个新的任务目录并返回 (job_id, job_dir)。
    """
    jobs_root = get_web_jobs_root()
    job_id = uuid.uuid4().hex[:8]
    job_dir = jobs_root / job_id
    job_dir.mkdir(parents=True, exist_ok=False)
    return job_id, job_dir


def cleanup_old_jobs(ttl_hours: float | None = None) -> None:
    """
    清理超过 TTL 的历史任务目录。

    - 默认 TTL 通过环境变量 VID2SUBS_WEB_JOBS_TTL_HOURS 控制（小时，默认 12）；
    - 设置为 0 或负数时不执行清理。
    """
    if ttl_hours is None:
        ttl_env = os.getenv("VID2SUBS_WEB_JOBS_TTL_HOURS", "12")
        try:
            ttl_hours = float(ttl_env)
        except ValueError:
            ttl_hours = 12.0

    if ttl_hours <= 0:
        return

    jobs_root = get_web_jobs_root()
    now = time.time()
    ttl_seconds = ttl_hours * 3600.0

    for entry in jobs_root.iterdir():
        if not entry.is_dir():
            continue
        try:
            mtime = entry.stat().st_mtime
        except OSError:
            continue
        if now - mtime > ttl_seconds:
            shutil.rmtree(entry, ignore_errors=True)


def write_job_meta(
    job_id: str,
    job_dir: Path,
    input_name: str,
    config: Vid2SubsConfig,
) -> None:
    """
    将任务的基本元信息写入 job.json，便于首页展示任务列表。
    """
    meta_path = job_dir / "job.json"
    created_at = datetime.now().isoformat(timespec="seconds")
    data: Dict[str, Any] = {
        "job_id": job_id,
        "input_name": input_name,
        "created_at": created_at,
        "source_lang": config.source_lang,
        "asr_backend": config.asr_backend,
        "translate_lang": config.translate_lang,
        "translation_engine": config.translation_engine,
    }
    try:
        meta_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        # 元信息写入失败不应影响主流程
        pass


def load_job_meta(job_dir: Path) -> Dict[str, Any] | None:
    """
    从任务目录读取 job.json，如果不存在或损坏则返回 None。
    """
    meta_path = job_dir / "job.json"
    if not meta_path.is_file():
        return None
    try:
        text = meta_path.read_text(encoding="utf-8")
        data = json.loads(text)
    except Exception:
        return None
    return data


def list_jobs(limit: int = 20) -> List[Dict[str, Any]]:
    """
    列出最近的若干任务（按创建时间或目录修改时间倒序）。
    """
    jobs_root = get_web_jobs_root()
    records: List[Dict[str, Any]] = []
    for entry in jobs_root.iterdir():
        if not entry.is_dir():
            continue
        meta = load_job_meta(entry)
        if not meta:
            continue
        job_id = str(meta.get("job_id") or entry.name)
        created_at = meta.get("created_at") or ""
        # 记录中附带目录路径，方便后续扩展（如删除任务）
        records.append(
            {
                "job_id": job_id,
                "input_name": meta.get("input_name") or "",
                "created_at": created_at,
                "translate_lang": meta.get("translate_lang"),
                "translation_engine": meta.get("translation_engine"),
            }
        )
    # 按 created_at 字符串倒序排序（ISO 格式可直接比较）
    records.sort(key=lambda r: r.get("created_at") or "", reverse=True)
    if limit > 0:
        records = records[:limit]
    return records
