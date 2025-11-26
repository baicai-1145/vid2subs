from __future__ import annotations

import os
from typing import List, Optional

import torch
from modelscope.hub.snapshot_download import snapshot_download  # type: ignore[import]
from transformers import (  # type: ignore[import]
    M2M100ForConditionalGeneration,
    M2M100Tokenizer,
)

from vid2subs.subtitles import SubtitleItem

from .translator import TranslationEngine


class M2M100Translator(TranslationEngine):
    """
    基于 facebook/m2m100_418M 的本地翻译引擎。

    默认行为：
    - 优先通过 ModelScope 从 https://modelscope.cn/models/facebook/m2m100_418M 下载模型；
    - 用户也可通过环境变量选择直接使用 transformers 从 HuggingFace Hub 下载：
      - VID2SUBS_M2M_SOURCE = "hf"
      - VID2SUBS_M2M_HF_MODEL_ID = "facebook/m2m100_418M"（可自定义）
    ModelScope 相关环境变量（可选）：
      - VID2SUBS_M2M_MODELSCOPE_ID（默认 "facebook/m2m100_418M"）
      - VID2SUBS_M2M_MODELSCOPE_CACHE（自定义缓存目录）
    """

    def __init__(
        self,
        device: Optional[str] = None,
        max_length: int = 256,
    ) -> None:
        self.model_source = os.getenv("VID2SUBS_M2M_SOURCE", "modelscope").lower()
        self.modelscope_id = os.getenv("VID2SUBS_M2M_MODELSCOPE_ID", "facebook/m2m100_418M")
        self.modelscope_cache = os.getenv("VID2SUBS_M2M_MODELSCOPE_CACHE", None)
        self.hf_model_id = os.getenv("VID2SUBS_M2M_HF_MODEL_ID", "facebook/m2m100_418M")
        self._device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.max_length = max_length

        self._tokenizer: M2M100Tokenizer | None = None
        self._model: M2M100ForConditionalGeneration | None = None

    @staticmethod
    def _normalize_lang(code: str, is_source: bool) -> str:
        """
        将外部传入的语言代码规范化为 M2M100 支持的形式。

        - 统一为小写；
        - 常见别名与预设（EN/EU/zh-CN 等）映射到标准代码。
        """
        if not code:
            return "en"
        raw = code.strip()
        if not raw:
            return "en"

        upper = raw.upper()
        if upper in {"EN", "EU"}:
            # Nemo 的 EN/EU 预设都输出英文文本，这里统一视为 en
            return "en"

        low = raw.lower().replace("_", "-")
        mapping = {
            "en-us": "en",
            "en-gb": "en",
            "en": "en",
            "zh": "zh",
            "zh-cn": "zh",
            "zh-hans": "zh",
            "zh-hant": "zh",
            "zh-tw": "zh",
        }
        return mapping.get(low, low)

    def _ensure_model(self) -> None:
        if self._model is not None and self._tokenizer is not None:
            return

        if self.model_source == "hf":
            model_dir = self.hf_model_id
        else:
            # 通过 ModelScope 下载到本地
            model_dir = snapshot_download(
                self.modelscope_id,
                cache_dir=self.modelscope_cache,
            )

        tokenizer = M2M100Tokenizer.from_pretrained(model_dir)
        model = M2M100ForConditionalGeneration.from_pretrained(model_dir)
        model.to(self._device)
        self._tokenizer = tokenizer
        self._model = model

    def _translate_batch(
        self,
        texts: List[str],
        source_lang: str,
        target_lang: str,
    ) -> List[str]:
        assert self._tokenizer is not None
        assert self._model is not None

        tokenizer = self._tokenizer
        model = self._model

        tokenizer.src_lang = source_lang
        encoded = tokenizer(
            texts,
            return_tensors="pt",
            padding=True,
            truncation=True,
            max_length=self.max_length,
        )
        encoded = {k: v.to(self._device) for k, v in encoded.items()}

        forced_bos_token_id = tokenizer.get_lang_id(target_lang)
        with torch.no_grad():
            generated_tokens = model.generate(
                **encoded,
                forced_bos_token_id=forced_bos_token_id,
                max_length=self.max_length,
            )

        outputs = tokenizer.batch_decode(generated_tokens, skip_special_tokens=True)
        return [out.strip() for out in outputs]

    def translate_subtitles(
        self,
        items: List[SubtitleItem],
        source_lang: str,
        target_lang: str,
    ) -> List[str]:
        self._ensure_model()
        assert self._tokenizer is not None and self._model is not None

        texts = [item.text for item in items]
        if not texts:
            return []

        # 为简单起见，目前采用单批次翻译；如需更细粒度的分批，可在后续扩展。
        src = self._normalize_lang(source_lang, is_source=True)
        tgt = self._normalize_lang(target_lang, is_source=False)
        translations = self._translate_batch(texts, src, tgt)
        if len(translations) != len(items):
            # 防御性处理：长度不一致时进行截断/填充
            if len(translations) > len(items):
                translations = translations[: len(items)]
            else:
                translations.extend([""] * (len(items) - len(translations)))
        return translations
