from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Tuple

import requests

from vid2subs.subtitles import SubtitleItem

from .translator import TranslationEngine


def _load_prompt(name: str) -> str:
    """
    从项目根目录的 prompts/ 下加载指定的 prompt 模板。

    为保持简单，当前实现假定项目结构与源码仓库一致：
    - <project_root>/prompts/<name>
    """
    # __file__ 示例路径：
    #   <project_root>/src/vid2subs/translate/llm_translator.py
    # parents[0] -> src/vid2subs/translate
    # parents[1] -> src/vid2subs
    # parents[2] -> src
    # parents[3] -> project_root
    root = Path(__file__).resolve().parents[3]
    prompt_path = root / "prompts" / name
    if not prompt_path.is_file():
        raise FileNotFoundError(f"Prompt file not found: {prompt_path}")
    return prompt_path.read_text(encoding="utf-8")


class LLMTranslator(TranslationEngine):
    """
    使用外部 LLM 服务进行高级翻译的引擎。

    所有与 LLM 的交互都采用 JSON 格式，并遵循 prompts/ 目录中定义的协议。

    环境变量约定（来自 .env 或系统环境）：
      - VID2SUBS_LLM_URL               # 必填，LLM 接口完整 URL（假定兼容 OpenAI Chat Completions）
      - VID2SUBS_LLM_MODEL             # 必填，模型名称
      - VID2SUBS_LLM_API_KEY           # 可选，用于 Authorization: Bearer
      - VID2SUBS_LLM_CTX_TOKENS        # 可选，整型，上下文窗口 token 数（目前仅用于参考）
      - VID2SUBS_LLM_TEXT_LIMIT        # 可选，生成翻译提示词时的文本长度上限（字符），默认 8000
      - VID2SUBS_LLM_TRANSLATE_TEXT_LIMIT # 可选，单次翻译调用的文本长度上限（字符），默认 6000
    """

    def __init__(self) -> None:
        url = os.getenv("VID2SUBS_LLM_URL")
        model = os.getenv("VID2SUBS_LLM_MODEL")
        if not url or not model:
            raise RuntimeError(
                "LLMTranslator requires VID2SUBS_LLM_URL and VID2SUBS_LLM_MODEL to be set."
            )
        self.url = url
        self.model = model
        self.api_key = os.getenv("VID2SUBS_LLM_API_KEY")
        self.ctx_tokens = int(os.getenv("VID2SUBS_LLM_CTX_TOKENS", "8192"))
        self.text_limit = int(os.getenv("VID2SUBS_LLM_TEXT_LIMIT", "8000"))
        self.translate_text_limit = int(
            os.getenv("VID2SUBS_LLM_TRANSLATE_TEXT_LIMIT", "6000")
        )
        # 调试开关：设置 VID2SUBS_LLM_DEBUG=1 时，会打印请求与原始响应
        self.debug = os.getenv("VID2SUBS_LLM_DEBUG", "").strip() == "1"

        http_proxy = os.getenv("VID2SUBS_HTTP_PROXY")
        https_proxy = os.getenv("VID2SUBS_HTTPS_PROXY")
        proxies: dict[str, str] = {}
        if http_proxy:
            proxies["http"] = http_proxy
        if https_proxy:
            proxies["https"] = https_proxy
        self.proxies = proxies or None

    def _call_chat(self, system_prompt: str, user_payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        使用 OpenAI Chat Completions 兼容接口调用外部 LLM。
        """
        headers = {
            "Content-Type": "application/json",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
        ]
        body = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.2,
        }

        if self.debug:
            print("\n[LLM DEBUG] 请求体预览:")
            try:
                body_preview = json.dumps(body, ensure_ascii=False)[:2000]
                print(body_preview)
            except Exception:
                print("无法序列化请求体预览。")

        response = requests.post(
            self.url,
            headers=headers,
            data=json.dumps(body),
            timeout=60,
            proxies=self.proxies,
        )
        response.raise_for_status()

        try:
            data = response.json()
        except ValueError as json_err:
            snippet = response.text[:500]
            raise RuntimeError(
                f"LLM response is not valid JSON, first 500 chars: {snippet}"
            ) from json_err

        # 兼容多种常见返回格式，并给出更友好的错误信息
        choices = data.get("choices")
        if not choices:
            raise RuntimeError(
                f"LLM response missing 'choices' field, got: {list(data.keys())}"
            )

        first = choices[0]
        content: str | None = None

        # OpenAI Chat: choices[0].message.content
        message = first.get("message")
        if isinstance(message, dict):
            content = message.get("content")

        # 某些实现可能直接在 text 字段返回
        if content is None and "text" in first:
            content = first.get("text")

        if not content:
            raise RuntimeError(
                f"LLM response missing 'content'/'text' in first choice: {first}"
            )

        if self.debug:
            print("\n[LLM DEBUG] 原始 content 预览:")
            try:
                print(str(content)[:2000])
            except Exception:
                print("无法打印 content 预览。")

        try:
            return json.loads(content)
        except json.JSONDecodeError as parse_err:
            snippet = content[:500]
            raise RuntimeError(
                f"LLM returned non-JSON content (first 500 chars): {snippet}"
            ) from parse_err

    def _total_text_length(self, items: List[SubtitleItem]) -> int:
        return sum(len(item.text) for item in items)

    def _build_subtitle_json(self, items: List[SubtitleItem]) -> List[Dict[str, Any]]:
        return [
            {
                "index": item.index,
                "start": item.start,
                "end": item.end,
                "text": item.text,
            }
            for item in items
        ]

    def _plan_for_short_text(
        self,
        items: List[SubtitleItem],
        source_lang: str,
        target_lang: str,
    ) -> Tuple[str, str]:
        """
        短文本场景：一次性生成 translation_prompt。
        返回 (video_summary, translation_prompt)。
        """
        system_prompt = _load_prompt("llm_short_text_prompt.md")
        user_payload = {
            "source_language": source_lang,
            "target_language": target_lang,
            "subtitles": self._build_subtitle_json(items),
        }
        result = self._call_chat(system_prompt, user_payload)
        video_summary = result.get("video_summary", "") or ""
        translation_prompt = result.get("translation_prompt", "")
        return video_summary, translation_prompt

    def _summarize_chunks(
        self,
        items: List[SubtitleItem],
        source_lang: str,
        target_lang: str,
    ) -> List[Dict[str, Any]]:
        """
        长文本场景：按 text_limit 将字幕分块，逐块生成详细 summary。
        返回 [{"chunk_index": int, "video_summary": str}, ...]
        """
        system_prompt = _load_prompt("llm_chunk_summary_prompt.md")
        chunks: List[List[SubtitleItem]] = []
        current_chunk: List[SubtitleItem] = []
        current_len = 0
        for item in items:
            item_len = len(item.text)
            if current_chunk and current_len + item_len > self.text_limit:
                chunks.append(current_chunk)
                current_chunk = []
                current_len = 0
            current_chunk.append(item)
            current_len += item_len
        if current_chunk:
            chunks.append(current_chunk)

        summaries: List[Dict[str, Any]] = []
        for idx, chunk in enumerate(chunks, start=1):
            user_payload = {
                "source_language": source_lang,
                "target_language": target_lang,
                "chunk_index": idx,
                "subtitles": self._build_subtitle_json(chunk),
            }
            result = self._call_chat(system_prompt, user_payload)
            chunk_summary = {
                "chunk_index": idx,
                "video_summary": result.get("video_summary", ""),
            }
            summaries.append(chunk_summary)
        return summaries

    def _plan_from_summaries(
        self,
        summaries: List[Dict[str, Any]],
        source_lang: str,
        target_lang: str,
    ) -> Tuple[str, str]:
        """
        基于所有分块 summary 生成全局 video_summary 和 translation_prompt。
        """
        system_prompt = _load_prompt("llm_global_prompt_from_summaries.md")
        user_payload = {
            "source_language": source_lang,
            "target_language": target_lang,
            "chunk_summaries": summaries,
        }
        result = self._call_chat(system_prompt, user_payload)
        video_summary = result.get("video_summary", "")
        translation_prompt = result.get("translation_prompt", "")
        return video_summary, translation_prompt

    def _translate_in_batches(
        self,
        items: List[SubtitleItem],
        source_lang: str,
        target_lang: str,
        video_summary: str,
        translation_prompt: str,
    ) -> List[str]:
        """
        使用 translation_prompt 作为系统上下文，分批调用 LLM 进行翻译。
        """
        system_prompt = _load_prompt("llm_translation_prompt.md")

        batches: List[List[SubtitleItem]] = []
        current_batch: List[SubtitleItem] = []
        current_len = 0
        for item in items:
            item_len = len(item.text)
            if current_batch and current_len + item_len > self.translate_text_limit:
                batches.append(current_batch)
                current_batch = []
                current_len = 0
            current_batch.append(item)
            current_len += item_len
        if current_batch:
            batches.append(current_batch)

        translations_by_index: Dict[int, str] = {}

        for batch in batches:
            user_payload = {
                "source_language": source_lang,
                "target_language": target_lang,
                "video_summary": video_summary,
                "translation_prompt": translation_prompt,
                "subtitles": self._build_subtitle_json(batch),
            }
            result = self._call_chat(system_prompt, user_payload)
            batch_translations = result.get("translations", []) or []
            for entry in batch_translations:
                try:
                    idx = int(entry.get("index"))
                except (TypeError, ValueError):
                    continue
                translated_text = entry.get("translated_text", "")
                translations_by_index[idx] = translated_text

        # 按原始顺序重组结果
        return [translations_by_index.get(item.index, "") for item in items]

    def translate_subtitles(
        self,
        items: List[SubtitleItem],
        source_lang: str,
        target_lang: str,
    ) -> List[str]:
        if not items:
            return []

        total_len = self._total_text_length(items)
        if total_len <= self.text_limit:
            video_summary, translation_prompt = self._plan_for_short_text(
                items,
                source_lang=source_lang,
                target_lang=target_lang,
            )
        else:
            summaries = self._summarize_chunks(
                items,
                source_lang=source_lang,
                target_lang=target_lang,
            )
            video_summary, translation_prompt = self._plan_from_summaries(
                summaries,
                source_lang=source_lang,
                target_lang=target_lang,
            )

        return self._translate_in_batches(
            items,
            source_lang=source_lang,
            target_lang=target_lang,
            video_summary=video_summary,
            translation_prompt=translation_prompt,
        )
