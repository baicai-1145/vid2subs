from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Tuple
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
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
        # LLM 并行请求数（默认 1，推荐根据模型/网关能力设置，例如 3）
        self.max_workers = max(
            1, int(os.getenv("VID2SUBS_LLM_CONCURRENCY", "1") or "1")
        )
        # 调试开关：设置 VID2SUBS_LLM_DEBUG=1 时，会打印请求与原始响应
        self.debug = os.getenv("VID2SUBS_LLM_DEBUG", "").strip() == "1"

        # 结构化输出配置：
        # VID2SUBS_LLM_STRUCTURED:
        #   - "none"        : 不启用结构化输出（默认）
        #   - "translation" : 只在翻译阶段使用 json_schema
        #   - "all"         : 预留，未来可扩展到所有阶段
        self.structured_mode = os.getenv(
            "VID2SUBS_LLM_STRUCTURED", "none"
        ).strip().lower()
        # 某些非 OpenAI 平台可能使用不同的参数名（例如 "format"），允许用户在 .env 中覆盖
        self.response_format_key = os.getenv(
            "VID2SUBS_LLM_RESPONSE_FORMAT_KEY", "response_format"
        ).strip()

        # 代理配置
        http_proxy = os.getenv("VID2SUBS_HTTP_PROXY")
        https_proxy = os.getenv("VID2SUBS_HTTPS_PROXY")
        proxies: dict[str, str] = {}
        if http_proxy:
            proxies["http"] = http_proxy
        if https_proxy:
            proxies["https"] = https_proxy
        self.proxies = proxies or None

        # 调试日志文件路径（仅在 debug 模式下启用）
        self.log_path: Path | None = None
        if self.debug:
            root = Path(__file__).resolve().parents[3]
            log_dir = root / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            self.log_path = log_dir / "llm_debug.log"

        # 用于清理译文中的控制字符（包括 \u007f）
        self._control_chars_pattern = re.compile(r"[\u0000-\u001F\u007F]")

    def _debug_print(self, title: str, payload: Any, limit: int | None = 4000) -> None:
        """
        安全打印调试信息，避免编码错误，并对超长内容进行可选截断。
        """
        if not self.debug:
            return
        try:
            # 控制台使用 ASCII，避免 Windows 终端编码问题
            try:
                console_text = json.dumps(payload, ensure_ascii=True, indent=2)
            except TypeError:
                console_text = repr(payload)

            if limit is not None and len(console_text) > limit:
                display = console_text[:limit] + f"\n... (truncated, {len(console_text)} chars total)"
            else:
                display = console_text

            print(f"\n[LLM DEBUG] {title}")
            print(display)

            # 日志文件使用 UTF-8，保留原始 Unicode 字符，便于阅读
            if self.log_path is not None:
                try:
                    file_text = json.dumps(payload, ensure_ascii=False, indent=2)
                except TypeError:
                    file_text = repr(payload)
                with self.log_path.open("a", encoding="utf-8") as f:
                    f.write(f"\n[LLM DEBUG] {title}\n")
                    f.write(file_text)
                    f.write("\n")
        except Exception as debug_err:
            print(f"[LLM DEBUG] 打印调试信息失败: {debug_err!r}")

    @staticmethod
    def _describe_language(code: str) -> str:
        """
        将内部使用的语言代码转换为更易读的说明，用于传给 LLM 的 target_language 字段。

        - 针对 LLM，只需给出“目标语言描述”，不会影响底层翻译逻辑；
        - 未知代码原样返回，避免错误映射。
        """
        if not code:
            return "auto"
        raw = code.strip()
        lower = raw.lower()

        # 100+1 个预设：auto + M2M100 覆盖的 100 种语言
        mapping: Dict[str, str] = {
            "auto": "auto",
            "af": "Afrikaans (af)",
            "am": "Amharic (am)",
            "ar": "Arabic (ar)",
            "ast": "Asturian (ast)",
            "az": "Azerbaijani (az)",
            "ba": "Bashkir (ba)",
            "be": "Belarusian (be)",
            "bg": "Bulgarian (bg)",
            "bn": "Bengali (bn)",
            "br": "Breton (br)",
            "bs": "Bosnian (bs)",
            "ca": "Catalan; Valencian (ca)",
            "ceb": "Cebuano (ceb)",
            "cs": "Czech (cs)",
            "cy": "Welsh (cy)",
            "da": "Danish (da)",
            "de": "German (de)",
            "el": "Greek (el)",
            "en": "English (en)",
            "es": "Spanish (es)",
            "et": "Estonian (et)",
            "fa": "Persian (fa)",
            "ff": "Fulah (ff)",
            "fi": "Finnish (fi)",
            "fr": "French (fr)",
            "fy": "Western Frisian (fy)",
            "ga": "Irish (ga)",
            "gd": "Gaelic; Scottish Gaelic (gd)",
            "gl": "Galician (gl)",
            "gu": "Gujarati (gu)",
            "ha": "Hausa (ha)",
            "he": "Hebrew (he)",
            "hi": "Hindi (hi)",
            "hr": "Croatian (hr)",
            "ht": "Haitian; Haitian Creole (ht)",
            "hu": "Hungarian (hu)",
            "hy": "Armenian (hy)",
            "id": "Indonesian (id)",
            "ig": "Igbo (ig)",
            "ilo": "Iloko (ilo)",
            "is": "Icelandic (is)",
            "it": "Italian (it)",
            "ja": "Japanese (ja)",
            "jv": "Javanese (jv)",
            "ka": "Georgian (ka)",
            "kk": "Kazakh (kk)",
            "km": "Central Khmer (km)",
            "kn": "Kannada (kn)",
            "ko": "Korean (ko)",
            "lb": "Luxembourgish; Letzeburgesch (lb)",
            "lg": "Ganda (lg)",
            "ln": "Lingala (ln)",
            "lo": "Lao (lo)",
            "lt": "Lithuanian (lt)",
            "lv": "Latvian (lv)",
            "mg": "Malagasy (mg)",
            "mk": "Macedonian (mk)",
            "ml": "Malayalam (ml)",
            "mn": "Mongolian (mn)",
            "mr": "Marathi (mr)",
            "ms": "Malay (ms)",
            "my": "Burmese (my)",
            "ne": "Nepali (ne)",
            "nl": "Dutch; Flemish (nl)",
            "no": "Norwegian (no)",
            "ns": "Northern Sotho (ns)",
            "oc": "Occitan (post 1500) (oc)",
            "or": "Oriya (or)",
            "pa": "Panjabi; Punjabi (pa)",
            "pl": "Polish (pl)",
            "ps": "Pushto; Pashto (ps)",
            "pt": "Portuguese (pt)",
            "ro": "Romanian; Moldavian; Moldovan (ro)",
            "ru": "Russian (ru)",
            "sd": "Sindhi (sd)",
            "si": "Sinhala; Sinhalese (si)",
            "sk": "Slovak (sk)",
            "sl": "Slovenian (sl)",
            "so": "Somali (so)",
            "sq": "Albanian (sq)",
            "sr": "Serbian (sr)",
            "ss": "Swati (ss)",
            "su": "Sundanese (su)",
            "sv": "Swedish (sv)",
            "sw": "Swahili (sw)",
            "ta": "Tamil (ta)",
            "th": "Thai (th)",
            "tl": "Tagalog (tl)",
            "tn": "Tswana (tn)",
            "tr": "Turkish (tr)",
            "uk": "Ukrainian (uk)",
            "ur": "Urdu (ur)",
            "uz": "Uzbek (uz)",
            "vi": "Vietnamese (vi)",
            "wo": "Wolof (wo)",
            "xh": "Xhosa (xh)",
            "yi": "Yiddish (yi)",
            "yo": "Yoruba (yo)",
            "zh": "Chinese (zh)",
            "zu": "Zulu (zu)",
        }

        return mapping.get(lower, raw)

    def _call_chat(
        self,
        system_prompt: str,
        user_payload: Dict[str, Any],
        response_format: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
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
        if response_format is not None and self.response_format_key:
            body[self.response_format_key] = response_format

        self._debug_print("请求体预览", body)

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

        self._debug_print("完整响应 JSON", data, limit=4000)

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

        self._debug_print("原始 content 内容", content, limit=4000)

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
        target_desc = self._describe_language(target_lang)
        user_payload = {
            "source_language": source_lang,
            "target_language": target_desc,
            "subtitles": self._build_subtitle_json(items),
        }
        self._debug_print(
            "短文本场景 - subtitles 文本",
            [item.text for item in items],
        )
        # 仅在 structured_mode=all 时，对规划阶段启用结构化输出
        response_format: Dict[str, Any] | None = None
        if self.structured_mode == "all" and self.response_format_key:
            schema: Dict[str, Any] = {
                "type": "object",
                "properties": {
                    "video_summary": {"type": "string"},
                    "translation_prompt": {"type": "string"},
                    "translations": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "index": {"type": "integer"},
                                "translated_text": {"type": "string"},
                            },
                            "required": ["index", "translated_text"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["video_summary", "translation_prompt", "translations"],
                "additionalProperties": False,
            }
            response_format = {
                "type": "json_schema",
                "json_schema": {
                    "name": "vid2subs_plan_short",
                    "strict": True,
                    "schema": schema,
                },
            }

        result = self._call_chat(system_prompt, user_payload, response_format=response_format)
        video_summary = result.get("video_summary", "") or ""
        translation_prompt = result.get("translation_prompt", "")
        self._debug_print(
            "短文本场景 - 生成的 translation_prompt",
            {"video_summary": video_summary, "translation_prompt": translation_prompt},
            limit=None,
        )
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
        target_desc = self._describe_language(target_lang)
        response_format: Dict[str, Any] | None = None
        if self.structured_mode == "all" and self.response_format_key:
            schema: Dict[str, Any] = {
                "type": "object",
                "properties": {
                    "video_summary": {"type": "string"},
                    "translation_prompt": {"type": "string"},
                    "translations": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "index": {"type": "integer"},
                                "translated_text": {"type": "string"},
                            },
                            "required": ["index", "translated_text"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["video_summary", "translation_prompt", "translations"],
                "additionalProperties": False,
            }
            response_format = {
                "type": "json_schema",
                "json_schema": {
                    "name": "vid2subs_chunk_summary",
                    "strict": True,
                    "schema": schema,
                },
            }
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
            chunk_text = "\n".join(item.text for item in chunk)
            self._debug_print(
                f"长文本场景 - 分块字幕文本 chunk={idx}",
                {"chunk_index": idx, "text": chunk_text},
            )
            user_payload = {
                "source_language": source_lang,
                "target_language": target_desc,
                "chunk_index": idx,
                "subtitles": self._build_subtitle_json(chunk),
            }
            result = self._call_chat(system_prompt, user_payload, response_format=response_format)
            chunk_summary = {
                "chunk_index": idx,
                "video_summary": result.get("video_summary", ""),
            }
            self._debug_print(
                f"长文本场景 - 分块 summary chunk={idx}",
                chunk_summary,
            )
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
        target_desc = self._describe_language(target_lang)
        response_format: Dict[str, Any] | None = None
        if self.structured_mode == "all" and self.response_format_key:
            schema: Dict[str, Any] = {
                "type": "object",
                "properties": {
                    "video_summary": {"type": "string"},
                    "translation_prompt": {"type": "string"},
                    "translations": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "index": {"type": "integer"},
                                "translated_text": {"type": "string"},
                            },
                            "required": ["index", "translated_text"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["video_summary", "translation_prompt", "translations"],
                "additionalProperties": False,
            }
            response_format = {
                "type": "json_schema",
                "json_schema": {
                    "name": "vid2subs_global_plan",
                    "strict": True,
                    "schema": schema,
                },
            }
        user_payload = {
            "source_language": source_lang,
            "target_language": target_desc,
            "chunk_summaries": summaries,
        }
        self._debug_print(
            "长文本场景 - chunk summaries 输入",
            user_payload,
        )
        result = self._call_chat(system_prompt, user_payload, response_format=response_format)
        video_summary = result.get("video_summary", "")
        translation_prompt = result.get("translation_prompt", "")
        self._debug_print(
            "长文本场景 - 全局 summary 与 translation_prompt",
            {"video_summary": video_summary, "translation_prompt": translation_prompt},
            limit=None,
        )
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
        base_system_prompt = _load_prompt("llm_translation_prompt.md")
        # 将前面规划好的 translation_prompt 追加到 system prompt 中，
        # 使其作为系统级翻译风格/策略说明。
        system_prompt = (
            f"{base_system_prompt}\n\n"
            "----- TRANSLATION INSTRUCTIONS (from previous planning steps) -----\n"
            f"{translation_prompt}\n"
        )

        # 仅在结构化输出模式开启时，为翻译阶段构建 JSON Schema
        translation_response_format: Dict[str, Any] | None = None
        if self.structured_mode in {"translation", "all"} and self.response_format_key:
            translation_schema: Dict[str, Any] = {
                "type": "object",
                "properties": {
                    "video_summary": {"type": "string"},
                    "translation_prompt": {"type": "string"},
                    "translations": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "index": {"type": "integer"},
                                "translated_text": {"type": "string"},
                            },
                            "required": ["index", "translated_text"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["video_summary", "translation_prompt", "translations"],
                "additionalProperties": False,
            }
            translation_response_format = {
                "type": "json_schema",
                "json_schema": {
                    "name": "vid2subs_translation",
                    "strict": True,
                    "schema": translation_schema,
                },
            }

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

        def process_batch(batch: List[SubtitleItem]) -> Dict[int, str]:
            user_payload = {
                "source_language": source_lang,
                "target_language": target_lang,
                # 为节省 token，这里不再传入长 video_summary，仅保留占位字段
                "video_summary": "",
                "subtitles": self._build_subtitle_json(batch),
            }
            self._debug_print(
                "翻译阶段 - 单个 batch 输入",
                {
                    "source_language": source_lang,
                    "target_language": target_lang,
                    "video_summary": "",
                    "subtitle_count": len(batch),
                },
            )
            result = self._call_chat(
                system_prompt,
                user_payload,
                response_format=translation_response_format,
            )
            batch_translations = result.get("translations", []) or []
            local_map: Dict[int, str] = {}
            for entry in batch_translations:
                try:
                    idx = int(entry.get("index"))
                except (TypeError, ValueError):
                    continue
                translated_text = entry.get("translated_text", "")
                # 清理控制字符，避免出现 \u007f 等不可见字符
                translated_text = self._control_chars_pattern.sub("", translated_text)
                local_map[idx] = translated_text
            return local_map

        # 并行执行每个 batch 的翻译调用
        worker_count = min(self.max_workers, len(batches))
        if worker_count <= 1:
            for batch in batches:
                batch_map = process_batch(batch)
                translations_by_index.update(batch_map)
        else:
            with ThreadPoolExecutor(max_workers=worker_count) as executor:
                future_to_idx = {
                    executor.submit(process_batch, batch): i
                    for i, batch in enumerate(batches)
                }
                for future in as_completed(future_to_idx):
                    batch_idx = future_to_idx[future]
                    try:
                        batch_map = future.result()
                    except Exception as exc:
                        raise RuntimeError(
                            f"LLM batch {batch_idx} failed: {exc}"
                        ) from exc
                    translations_by_index.update(batch_map)

        # 按原始顺序重组结果
        self._debug_print(
            "翻译阶段 - translations_by_index",
            translations_by_index,
            limit=None,
        )
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
        self._debug_print(
            "总文本长度与 TEXT_LIMIT",
            {
                "total_len": total_len,
                "text_limit": self.text_limit,
                "is_long_text": total_len > self.text_limit,
            },
        )
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
