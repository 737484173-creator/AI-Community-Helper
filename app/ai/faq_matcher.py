from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

from app.database.repositories.faq_repository import FAQRepository


TOKEN_PATTERN = re.compile(r"[a-z0-9]+", re.IGNORECASE)


@dataclass(frozen=True)
class FAQMatch:
    faq_id: int
    category: str
    question: str
    answer: str
    score: float


class FAQMatcher:
    def __init__(self, db_path: str | Path | None = None) -> None:
        self.faqs = FAQRepository(db_path)

    def find_best_match(self, message: str, min_score: float = 0.5) -> FAQMatch | None:
        best_match: FAQMatch | None = None
        for row in self.faqs.list_enabled():
            score = _score_match(
                message=message,
                question=str(row["question"]),
                answer=str(row["answer"]),
                keywords=str(row["keywords"] or ""),
                category=str(row["category"]),
            )
            if best_match is None or score > best_match.score:
                best_match = FAQMatch(
                    faq_id=int(row["id"]),
                    category=str(row["category"]),
                    question=str(row["question"]),
                    answer=str(row["answer"]),
                    score=score,
                )

        if best_match is None or best_match.score < min_score:
            return None
        return best_match


def _score_match(
    message: str,
    question: str,
    keywords: str,
    category: str,
    answer: str = "",
) -> float:
    normalized_message = _normalize(message)
    normalized_question = _normalize(question)
    message_tokens = set(_tokens(normalized_message))
    searchable_tokens = set(_tokens(f"{normalized_question} {answer} {keywords} {category}"))

    if not normalized_message or not normalized_question:
        return 0.0

    ratio = SequenceMatcher(None, normalized_message, normalized_question).ratio()
    overlap = 0.0
    coverage = 0.0
    if message_tokens and searchable_tokens:
        overlap = len(message_tokens & searchable_tokens) / len(message_tokens | searchable_tokens)
        coverage = len(message_tokens & searchable_tokens) / len(message_tokens)

    phrase_bonus = 0.15 if normalized_message in normalized_question else 0.0
    keyword_bonus = 0.1 if keywords and message_tokens & set(_tokens(keywords)) else 0.0
    category_bonus = 0.08 if category.lower() in normalized_message else 0.0
    return min(
        1.0,
        ratio * 0.35
        + overlap * 0.15
        + coverage * 0.4
        + phrase_bonus
        + keyword_bonus
        + category_bonus,
    )


def _normalize(text: str) -> str:
    return " ".join(text.lower().strip().split())


def _tokens(text: str) -> list[str]:
    return TOKEN_PATTERN.findall(text.lower())
