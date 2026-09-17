from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.database.repositories.faq_repository import FAQRepository
from app.database.repositories.message_repository import MessageRepository
from app.database.repositories.pending_ticket_repository import PendingTicketRepository
from app.utils.constants import MESSAGE_TYPE_FAQ


MAX_DISCORD_SELECT_OPTIONS = 25
MAX_QUESTION_OPTIONS_WITH_MANUAL = 24


@dataclass(frozen=True)
class FAQOption:
    id: int
    label: str
    description: str | None = None


@dataclass(frozen=True)
class FAQAnswer:
    faq_id: int
    category: str
    question: str
    answer: str


class FAQFlowService:
    def __init__(self, db_path: str | Path | None = None) -> None:
        self.faqs = FAQRepository(db_path)
        self.messages = MessageRepository(db_path)
        self.pending_tickets = PendingTicketRepository(db_path)

    def list_categories(self) -> list[str]:
        return self.faqs.list_categories()[:MAX_DISCORD_SELECT_OPTIONS]

    def list_questions(self, category: str) -> list[FAQOption]:
        rows = self.faqs.list_by_category(category)
        return [
            FAQOption(
                id=int(row["id"]),
                label=str(row["question"]),
                description=str(row["subcategory"]) if row["subcategory"] else None,
            )
            for row in rows[:MAX_QUESTION_OPTIONS_WITH_MANUAL]
        ]

    def get_answer(self, faq_id: int) -> FAQAnswer:
        row = self.faqs.get_by_id(faq_id)
        if row is None or not row["enabled"]:
            raise ValueError(f"FAQ item is not available: {faq_id}")

        return FAQAnswer(
            faq_id=int(row["id"]),
            category=str(row["category"]),
            question=str(row["question"]),
            answer=str(row["answer"]),
        )

    def mark_message_answered(
        self,
        message_id: int,
        answer: FAQAnswer,
    ) -> None:
        self.messages.update_ai_reply(
            message_id=message_id,
            ai_reply=answer.answer,
            message_type=MESSAGE_TYPE_FAQ,
        )

    def create_pending_ticket(
        self,
        discord_user_id: str,
        channel_id: str,
        original_message: str,
        selected_category: str | None = None,
        selected_question: str | None = None,
        issue_description: str | None = None,
        ticket_source: str = "FAQ_FLOW_UNRESOLVED",
    ) -> int:
        return self.pending_tickets.create(
            discord_user_id=discord_user_id,
            channel_id=channel_id,
            original_message=original_message,
            ticket_source=ticket_source,
            selected_category=selected_category,
            selected_question=selected_question,
            issue_description=issue_description,
        )
