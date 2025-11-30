from __future__ import annotations

import os
from pathlib import Path
import shutil
import json

from fastapi import FastAPI, HTTPException, Request, UploadFile, File, Form
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from vid2subs.env import load_dotenv_if_present
from vid2subs.config import Vid2SubsConfig
from .dependencies import (
    run_pipeline_for_web,
    create_job_dir,
    get_web_jobs_root,
    cleanup_old_jobs,
    write_job_meta,
    list_jobs,
)


def create_app() -> FastAPI:
    """
    创建并配置 FastAPI 应用。

    - 加载 .env 环境变量；
    - 挂载模板与静态资源目录；
    - 注册基础路由（/ 与 /health）。
    """
    load_dotenv_if_present()

    app = FastAPI(
        title="vid2subs Web",
        description="Web UI for vid2subs: 上传媒体文件并生成字幕。",
    )

    # 启动时尝试清理一次过期任务目录
    cleanup_old_jobs()

    base_dir = Path(__file__).resolve().parent
    templates = Jinja2Templates(directory=str(base_dir / "templates"))

    static_dir = base_dir / "static"
    if static_dir.is_dir():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    @app.get("/health", response_class=JSONResponse)
    async def health() -> dict[str, str]:
        """
        简单健康检查，用于部署与监控。
        """
        return {"status": "ok"}

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request) -> HTMLResponse:
        """
        首页：任务提交 + 最近任务列表。
        """
        jobs = list_jobs(limit=20)
        # 是否启用浏览器端预处理（由 .env 控制，而非前端开关）
        enable_browser_preprocess_env = os.getenv(
            "VID2SUBS_WEB_ENABLE_BROWSER_PREPROCESS", "1"
        ).strip().lower()
        browser_preprocess_enabled = enable_browser_preprocess_env not in {
            "0",
            "false",
            "no",
        }
        return templates.TemplateResponse(
            "index.html",
            {
                "request": request,
                "title": "vid2subs Web",
                "jobs": jobs,
                "browser_preprocess_enabled": browser_preprocess_enabled,
            },
        )


    @app.post("/api/jobs", response_class=JSONResponse)
    async def create_job_api(
        request: Request,
        file: UploadFile = File(...),
        lang: str = Form("EU"),
        asr_backend: str = Form("auto"),
        translate: str = Form(""),
        translation_engine: str = Form("google"),
        # 前端不再控制主 SRT 的双语/仅译文形态，这里参数保留以兼容旧表单，但不再使用
        bilingual: bool = Form(False),
        translated_only: bool = Form(False),
        no_vocal_sep: bool = Form(False),
        # SRT 输出策略简化：默认始终输出原文 SRT，
        # 若启用翻译，则额外输出译文 SRT，可选输出双语 SRT。
        output_srt_source: bool = Form(False),
        output_srt_translated: bool = Form(False),
        output_srt_bilingual: bool = Form(False),
        # Web 端默认总是生成 ASS，前端不再暴露开关
        output_ass: bool = Form(False),
    ) -> JSONResponse:
        """
        创建一个新的字幕生成任务。

        - 接收上传的媒体文件与参数；
        - 同步调用 Pipeline 生成字幕；
        - 返回包含任务信息与完整字幕列表的 JSON。
        """
        if not file.filename:
            raise HTTPException(status_code=400, detail="未选择要上传的文件。")

        # 每次请求前尝试清理过期任务
        cleanup_old_jobs()

        # 为本次请求创建独立任务目录
        job_id, job_dir = create_job_dir()
        input_path = job_dir / file.filename

        try:
            # 将上传内容落地到任务目录
            with input_path.open("wb") as f_out:
                # 控制最大上传大小，避免误上传超大文件
                max_mb_env = os.getenv("VID2SUBS_WEB_MAX_UPLOAD_MB", "1024")
                try:
                    max_mb = int(max_mb_env)
                except ValueError:
                    max_mb = 1024
                max_bytes = max_mb * 1024 * 1024

                copied = 0
                chunk_size = 1024 * 1024
                while True:
                    chunk = file.file.read(chunk_size)
                    if not chunk:
                        break
                    copied += len(chunk)
                    if copied > max_bytes:
                        # 删除本次任务目录后报错
                        shutil.rmtree(job_dir, ignore_errors=True)
                        raise HTTPException(
                            status_code=413,
                            detail=f"上传文件过大，超过限制 {max_mb} MB。",
                        )
                    f_out.write(chunk)

            # 基础类型校验（简单版本，避免明显错误）
            content_type = file.content_type or ""
            ext = input_path.suffix.lower()
            allowed_ext = {
                ".wav",
                ".mp3",
                ".flac",
                ".m4a",
                ".ogg",
                ".opus",
                ".mp4",
                ".mkv",
                ".mov",
                ".avi",
                ".webm",
                ".m4v",
            }
            if not (
                content_type.startswith("audio/")
                or content_type.startswith("video/")
                or ext in allowed_ext
            ):
                shutil.rmtree(job_dir, ignore_errors=True)
                raise HTTPException(
                    status_code=400,
                    detail="不支持的文件类型，请上传常见的视频或音频格式。",
                )

            # 构造与 CLI 一致的配置
            # 主 SRT 路径固定为任务目录下的 subtitles.srt。
            output_srt = job_dir / "subtitles.srt"
            translate_lang = translate.strip() or None

            # Web 版的简化策略：
            # - 不翻译时：仅输出主 SRT（原文）；
            # - 翻译时：始终输出主 SRT（原文）+ 译文 SRT，可选双语 SRT；
            # - ASS 默认总是生成（供 mkv 导出使用）。
            want_bilingual_srt = bool(output_srt_bilingual)
            # 译文 SRT：若用户显式勾选则强制生成，否则在有翻译时也默认生成
            want_translated_srt = bool(output_srt_translated) or bool(translate_lang)
            # 原文 SRT 始终通过主 SRT 输出，这里保留 output_srt_source 仅为兼容旧参数，不再单独生成 .source 版本
            want_source_srt = False

            config = Vid2SubsConfig.from_paths(
                input_path=input_path,
                output_audio_path=None,
                use_vocal_separation=not bool(no_vocal_sep),
                source_lang=lang,
                asr_backend=asr_backend,
                device=None,
                output_srt_path=output_srt,
                output_srt_source_path=want_source_srt,
                output_srt_translated_path=want_translated_srt,
                output_srt_bilingual_path=want_bilingual_srt,
                # Web 端默认总是生成 ASS 文件（subtitles.ass）
                output_ass_path=True,
                max_silence=1.0,
                max_chars_per_sentence=None,
                translate_lang=translate_lang,
                translation_engine=translation_engine,
                # 主 SRT 一律输出原文，双语/仅译文逻辑通过额外 SRT 文件表达
                bilingual=False,
                translated_only=False,
            )

            items = run_pipeline_for_web(config)

            # 写入任务元信息，供首页任务列表使用
            try:
                write_job_meta(job_id, job_dir, file.filename, config)
            except Exception:
                pass

        except HTTPException:
            # 直接透传上面的 HTTPException
            raise
        except Exception as exc:
            # 统一以 JSON 错误返回
            return JSONResponse(
                {"error": str(exc), "job_id": job_id},
                status_code=500,
            )

        # 构造下载链接
        download_main_url = None
        download_source_url = None
        download_translated_url = None
        download_bilingual_url = None
        download_ass_url = None

        if config.output_srt_path is not None and config.output_srt_path.is_file():
            download_main_url = request.url_for(
                "download_file", job_id=job_id, kind="main"
            )
        if (
            config.output_srt_source_path is not None
            and config.output_srt_source_path.is_file()
        ):
            download_source_url = request.url_for(
                "download_file", job_id=job_id, kind="source"
            )
        if (
            config.output_srt_translated_path is not None
            and config.output_srt_translated_path.is_file()
        ):
            download_translated_url = request.url_for(
                "download_file", job_id=job_id, kind="translated"
            )
        if (
            config.output_srt_bilingual_path is not None
            and config.output_srt_bilingual_path.is_file()
        ):
            download_bilingual_url = request.url_for(
                "download_file", job_id=job_id, kind="bilingual"
            )
        ass_path = getattr(config, "output_ass_path", None)
        if ass_path is not None and Path(ass_path).is_file():
            download_ass_url = request.url_for(
                "download_file", job_id=job_id, kind="ass"
            )

        # 完整字幕列表，供前端视频预览使用
        subtitles_payload = []
        for item in items:
            subtitles_payload.append(
                {
                    "index": item.index,
                    "start": float(item.start),
                    "end": float(item.end),
                    "text": item.text,
                    "translation": item.translation,
                }
            )

        # 将字幕 JSON 保存到磁盘，方便之后从任务列表中重新加载
        try:
            (job_dir / "subtitles.json").write_text(
                json.dumps(subtitles_payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            pass

        job_meta = {
            "job_id": job_id,
            "input_name": file.filename,
            "created_at": "",
            "translate_lang": config.translate_lang,
            "translation_engine": config.translation_engine,
        }

        # 将 URL 对象转换为字符串，避免 JSON 序列化错误
        download_main_url_str = str(download_main_url) if download_main_url else None
        download_source_url_str = (
            str(download_source_url) if download_source_url else None
        )
        download_translated_url_str = (
            str(download_translated_url) if download_translated_url else None
        )
        download_bilingual_url_str = (
            str(download_bilingual_url) if download_bilingual_url else None
        )

        return JSONResponse(
            {
                "job_id": job_id,
                "input_name": file.filename,
                "total_count": len(items),
                "download_main_url": download_main_url_str,
                "download_source_url": download_source_url_str,
                "download_translated_url": download_translated_url_str,
                "download_bilingual_url": download_bilingual_url_str,
                "download_ass_url": str(download_ass_url) if download_ass_url else None,
                "subtitles": subtitles_payload,
                "job": job_meta,
            }
        )

    @app.get("/download/{job_id}/{kind}", name="download_file")
    async def download_file(job_id: str, kind: str) -> FileResponse:
        """
        下载生成的字幕文件。

        当前仅支持 kind="srt"（主字幕文件）。
        """
        jobs_root = get_web_jobs_root()
        job_dir = jobs_root / job_id
        if not job_dir.is_dir():
            raise HTTPException(status_code=404, detail="任务不存在或已被清理。")

        if kind in {"srt", "main"}:
            path = job_dir / "subtitles.srt"
        elif kind == "source":
            path = job_dir / "subtitles.source.srt"
        elif kind == "translated":
            path = job_dir / "subtitles.translated.srt"
        elif kind == "bilingual":
            path = job_dir / "subtitles.bilingual.srt"
        elif kind == "ass":
            path = job_dir / "subtitles.ass"
        else:
            raise HTTPException(status_code=404, detail="不支持的下载类型。")

        if not path.is_file():
            raise HTTPException(status_code=404, detail="目标文件不存在。")

        return FileResponse(
            path,
            media_type="text/plain; charset=utf-8",
            filename=path.name,
        )

    @app.get("/api/jobs/{job_id}", response_class=JSONResponse)
    async def get_job_api(job_id: str) -> JSONResponse:
        """
        获取已有任务的字幕与下载信息（从磁盘读取，而不是重新跑 Pipeline）。
        """
        jobs_root = get_web_jobs_root()
        job_dir = jobs_root / job_id
        if not job_dir.is_dir():
            raise HTTPException(status_code=404, detail="任务不存在或已被清理。")

        subtitles_path = job_dir / "subtitles.json"
        if not subtitles_path.is_file():
            raise HTTPException(status_code=404, detail="该任务未找到字幕 JSON 文件。")

        try:
            subtitles_payload = json.loads(subtitles_path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise HTTPException(
                status_code=500,
                detail=f"加载字幕 JSON 失败: {exc}",
            ) from exc

        download_main_url = None
        download_source_url = None
        download_translated_url = None
        download_bilingual_url = None
        download_ass_url = None

        main_srt = job_dir / "subtitles.srt"
        if main_srt.is_file():
            download_main_url = f"/download/{job_id}/main"
        if (job_dir / "subtitles.source.srt").is_file():
            download_source_url = f"/download/{job_id}/source"
        if (job_dir / "subtitles.translated.srt").is_file():
            download_translated_url = f"/download/{job_id}/translated"
        if (job_dir / "subtitles.bilingual.srt").is_file():
            download_bilingual_url = f"/download/{job_id}/bilingual"
        if (job_dir / "subtitles.ass").is_file():
            download_ass_url = f"/download/{job_id}/ass"

        return JSONResponse(
            {
                "job_id": job_id,
                "total_count": len(subtitles_payload),
                "download_main_url": download_main_url,
                "download_source_url": download_source_url,
                "download_translated_url": download_translated_url,
                "download_bilingual_url": download_bilingual_url,
                "download_ass_url": download_ass_url,
                "subtitles": subtitles_payload,
            }
        )

    return app


# 供 uvicorn 等 ASGI 服务器直接引用
app = create_app()


def main() -> None:
    """
    本地启动 Web 服务的入口。

    可通过环境变量控制监听地址与端口：
      - VID2SUBS_WEB_HOST（默认 127.0.0.1）
      - VID2SUBS_WEB_PORT（默认 8000）
    """
    try:
        import uvicorn  # type: ignore[import]
    except ImportError as exc:  # pragma: no cover - 提示信息即可
        print("启动失败：未安装 uvicorn。请使用 `pip install vid2subs[web]` 安装 Web 依赖。")
        raise SystemExit(1) from exc

    host = os.getenv("VID2SUBS_WEB_HOST", "127.0.0.1")
    port_str = os.getenv("VID2SUBS_WEB_PORT", "8000")
    try:
        port = int(port_str)
    except ValueError:
        port = 8000

    uvicorn.run("vid2subs.web.app:app", host=host, port=port, reload=False)
