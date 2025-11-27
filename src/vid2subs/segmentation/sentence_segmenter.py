from __future__ import annotations

from dataclasses import dataclass
from typing import List
import os

from vid2subs.asr import Word


@dataclass
class Sentence:
    """
    由若干 Word 聚合而成的一句完整文本。
    """

    text: str
    start: float
    end: float
    words: List[Word]


SENTENCE_END_PUNCTUATION = "。.!！？?!…"
# 用于长度控制时尝试优先断句的可断标点（不包含引号、括号等）
BREAK_PUNCTUATION = "。.!！？?!…，,;；：:、"
NON_BREAK_PUNCTUATION = "“”‘’\"'()（）《》【】「」『』‹›"


def _strip_trailing_punct_if_enabled(text: str) -> str:
    """
    根据环境变量 VID2SUBS_STRIP_TRAILING_PUNCT 决定是否去除单条句子末尾的标点符号。

    - 默认关闭（环境变量不为 "1" 时）；
    - 仅去除末尾连续的常见标点，不影响引号、括号等。
    """
    if not text:
        return text
    if os.getenv("VID2SUBS_STRIP_TRAILING_PUNCT", "").strip() != "1":
        return text
    strip_chars = BREAK_PUNCTUATION
    t = text.rstrip()
    while t:
        last = t[-1]
        if last in strip_chars and last not in NON_BREAK_PUNCTUATION:
            t = t[:-1].rstrip()
            continue
        break
    return t


def _is_sentence_end_token(token: str) -> bool:
    stripped = token.strip()
    if not stripped:
        return False
    last_char = stripped[-1]
    return last_char in SENTENCE_END_PUNCTUATION


def words_to_sentences(
    words: List[Word],
    max_silence: float = 1.0,
    max_chars: int = 80,
) -> List[Sentence]:
    """
    将按时间排序的 Word 序列切分为句子。

    当前实现规则：
    - 句末标点（Sentence end punctuation）
    - 单句最大字符数（超过 max_chars 时，优先在最近的可断标点后断句）

    注意：max_silence 参数目前不再用于断句，仅保留以兼容旧接口。
    """
    if not words:
        return []

    sentences: List[Sentence] = []
    buffer_words: List[Word] = []
    buffer_text_parts: List[str] = []
    last_breakable_idx: int = -1

    def _update_last_breakable_index() -> None:
        nonlocal last_breakable_idx
        if not buffer_words:
            return
        token = buffer_words[-1].text
        stripped = token.strip()
        if not stripped:
            return
        last_char = stripped[-1]
        if last_char in BREAK_PUNCTUATION and last_char not in NON_BREAK_PUNCTUATION:
            last_breakable_idx = len(buffer_words) - 1

    def _flush_up_to(index: int) -> None:
        nonlocal buffer_words, buffer_text_parts, last_breakable_idx
        if not buffer_words:
            return
        if index < 0 or index >= len(buffer_words):
            index = len(buffer_words) - 1
        words_slice = buffer_words[: index + 1]
        texts_slice = buffer_text_parts[: index + 1]
        text = " ".join(texts_slice).strip()
        text = _strip_trailing_punct_if_enabled(text)
        if text:
            sent_start = words_slice[0].start
            sent_end = words_slice[-1].end
            sentences.append(
                Sentence(
                    text=text,
                    start=sent_start,
                    end=sent_end,
                    words=list(words_slice),
                )
            )
        # 保留剩余部分到下一个句子
        buffer_words = buffer_words[index + 1 :]
        buffer_text_parts = buffer_text_parts[index + 1 :]
        # 重新计算剩余部分中的可断标点位置
        last_breakable_idx = -1
        for i, w in enumerate(buffer_words):
            stripped = w.text.strip()
            if not stripped:
                continue
            last_char = stripped[-1]
            if last_char in BREAK_PUNCTUATION and last_char not in NON_BREAK_PUNCTUATION:
                last_breakable_idx = i

    for idx, w in enumerate(words):
        buffer_words.append(w)
        buffer_text_parts.append(w.text)
        _update_last_breakable_index()

        is_last_word = idx == len(words) - 1
        break_index: int | None = None

        # 标点断句：遇到句末标点时，直接在当前词处断句
        if _is_sentence_end_token(w.text):
            break_index = len(buffer_words) - 1
        else:
            # 长度控制：如果当前累计字符数超过 max_chars，优先在最近的可断标点后截断
            if len(" ".join(buffer_text_parts)) > max_chars:
                if last_breakable_idx >= 0:
                    break_index = last_breakable_idx
                else:
                    break_index = len(buffer_words) - 1

        if break_index is not None:
            _flush_up_to(break_index)

        if is_last_word and buffer_words:
            # 循环结束后，flush 剩余部分
            _flush_up_to(len(buffer_words) - 1)

    return sentences
