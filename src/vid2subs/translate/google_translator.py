from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List

import requests
from requests import HTTPError

from vid2subs.subtitles import SubtitleItem

from .translator import TranslationEngine


class GoogleTranslator(TranslationEngine):
    """
    使用 Google 翻译兼容接口的简单翻译引擎。

    默认使用官方接口：
      - https://translate.googleapis.com
    也可通过环境变量自定义：
      - VID2SUBS_GOOGLE_TRANSLATE_URL
        - 例如指向自建代理或反向代理服务

    代理配置（可选，通过 .env 或环境变量注入）：
      - VID2SUBS_HTTP_PROXY
      - VID2SUBS_HTTPS_PROXY

    当前实现采用「逐句调用」策略，优先保证稳定性与实现简单性。
    如需高并发和限速控制，可在后续阶段扩展。
    """

    def __init__(
        self,
        base_url: str | None = None,
        timeout: float = 10.0,
    ) -> None:
        env_url = os.getenv("VID2SUBS_GOOGLE_TRANSLATE_URL")
        if base_url is not None:
            self.base_url = base_url.rstrip("/")
        elif env_url:
            self.base_url = env_url.rstrip("/")
        else:
            self.base_url = "https://translate.googleapis.com"
        self.timeout = timeout

        # 单次请求的最大文本长度（字符），用于将多条字幕合并成一批发送
        self.text_limit = int(os.getenv("VID2SUBS_GOOGLE_TEXT_LIMIT", "1000") or "1000")

        # 并发配置：控制同时发起的最大请求数（默认 1）
        self.max_workers = max(
            1, int(os.getenv("VID2SUBS_GOOGLE_CONCURRENCY", "1") or "1")
        )

        http_proxy = os.getenv("VID2SUBS_HTTP_PROXY")
        https_proxy = os.getenv("VID2SUBS_HTTPS_PROXY")
        proxies: dict[str, str] = {}
        if http_proxy:
            proxies["http"] = http_proxy
        if https_proxy:
            proxies["https"] = https_proxy
        self.proxies = proxies or None

    def _endpoint(self) -> str:
        # 采用与 translate.googleapis.com 兼容的路径
        return f"{self.base_url}/translate_a/single"

    def _translate_text(self, text: str, source_lang: str, target_lang: str) -> str:
        if not text.strip():
            return ""
        params = {
            "client": "gtx",
            "sl": source_lang or "auto",
            "tl": target_lang,
            "dt": "t",
            "q": text,
        }

        def do_request(base_url: str) -> str:
            url = f"{base_url.rstrip('/')}/translate_a/single"
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) vid2subs/0.1.0",
            }
            resp = requests.get(
                url,
                params=params,
                timeout=self.timeout,
                headers=headers,
                proxies=self.proxies,
            )
            resp.raise_for_status()
            data = resp.json()
            translated_parts: list[str] = []
            if isinstance(data, list) and data:
                for part in data[0]:
                    if isinstance(part, list) and part:
                        translated_parts.append(str(part[0]))
            return "".join(translated_parts).strip() if translated_parts else text

        primary = self.base_url
        try:
            return do_request(primary)
        except HTTPError as http_err:
            raise
        except (requests.ConnectionError, requests.Timeout):
            raise

    def translate_subtitles(
        self,
        items: List[SubtitleItem],
        source_lang: str,
        target_lang: str,
    ) -> List[str]:
        translations: List[str] = ["" for _ in items]
        if not items:
            return translations

        src = source_lang or "auto"

        # 先按照 text_limit 将字幕 index 分组，每组的总字符数不超过限制
        groups: list[list[int]] = []
        current_group: list[int] = []
        current_len = 0
        for idx, item in enumerate(items):
            t = item.text or ""
            t_len = len(t)
            # 确保每组至少有一个元素
            if current_group and current_len + t_len > self.text_limit:
                groups.append(current_group)
                current_group = []
                current_len = 0
            current_group.append(idx)
            current_len += t_len
        if current_group:
            groups.append(current_group)

        # 串行模式：逐组请求
        worker_count = min(self.max_workers, len(groups))

        def process_group(group_indices: list[int]) -> tuple[list[int], list[str]]:
            # 按顺序拼接为一个文本块，用换行符分隔
            texts = [items[i].text or "" for i in group_indices]
            joined = "\n".join(texts)
            try:
                translated_block = self._translate_text(joined, src, target_lang)
            except Exception as exc:
                # 整组失败时，保留原文
                first_idx = items[group_indices[0]].index
                print(
                    f"Google 翻译失败（batch 起始 index={first_idx}）: {exc}. "
                    "该组将保留原文。"
                )
                return group_indices, texts

            # 尝试按照换行符拆分回每行字幕
            parts = translated_block.split("\n")
            if len(parts) != len(group_indices):
                # 拆分数量与原字幕数量不一致时，保守起见保留原文
                first_idx = items[group_indices[0]].index
                print(
                    f"Google 翻译返回行数与原始字幕数不一致（batch 起始 index={first_idx}），"
                    "该组将保留原文。"
                )
                return group_indices, texts
            return group_indices, [p.strip() for p in parts]

        if worker_count <= 1:
            for group in groups:
                idxs, trans = process_group(group)
                for i, text in zip(idxs, trans):
                    translations[i] = text
            return translations

        # 并行模式：按组并行请求 Google 翻译
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            future_to_group = {
                executor.submit(process_group, group): group for group in groups
            }
            for future in as_completed(future_to_group):
                idxs, trans = future.result()
                for i, text in zip(idxs, trans):
                    translations[i] = text

        return translations
