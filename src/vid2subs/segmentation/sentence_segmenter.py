from __future__ import annotations

from dataclasses import dataclass
from typing import List

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

    规则综合考虑：
    - 句末标点（Sentence end punctuation）
    - 相邻词之间的静音间隔（大于 max_silence 则强制断句）
    - 单句最大字符数（超过 max_chars 时优先在最近的标点后断句）
    """
    if not words:
        return []

    sentences: List[Sentence] = []
    buffer_words: List[Word] = []
    buffer_text_parts: List[str] = []
    current_start = words[0].start
    last_end = words[0].end

    def flush_buffer() -> None:
        nonlocal buffer_words, buffer_text_parts, current_start, last_end
        if not buffer_words:
            return
        text = " ".join(buffer_text_parts).strip()
        if not text:
            buffer_words = []
            buffer_text_parts = []
            return
        sent_start = buffer_words[0].start
        sent_end = buffer_words[-1].end
        sentences.append(
            Sentence(
                text=text,
                start=sent_start,
                end=sent_end,
                words=list(buffer_words),
            )
        )
        buffer_words = []
        buffer_text_parts = []

    for idx, w in enumerate(words):
        if not buffer_words:
            current_start = w.start
            last_end = w.end

        # 静音间隔（对于 0 时间戳的情况，间隔视为 0）
        gap = max(0.0, w.start - last_end)

        buffer_words.append(w)
        buffer_text_parts.append(w.text)
        last_end = w.end

        is_last_word = idx == len(words) - 1
        should_break = False

        # 静音断句
        if gap > max_silence:
            should_break = True

        # 标点断句
        if _is_sentence_end_token(w.text):
            should_break = True

        # 长度控制：如果当前累计字符数超过 max_chars，也尝试断句
        if len(" ".join(buffer_text_parts)) > max_chars:
            should_break = True

        if should_break or is_last_word:
            flush_buffer()

    return sentences

