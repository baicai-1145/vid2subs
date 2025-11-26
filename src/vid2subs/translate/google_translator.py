from __future__ import annotations

import os
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
        translations: List[str] = []
        src = source_lang or "auto"
        for item in items:
            translated = self._translate_text(item.text, src, target_lang)
            translations.append(translated)
        return translations
