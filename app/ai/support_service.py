from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.ai.ai_client import AIClient
from app.ai.chat_assistant import ChatAssistant
from app.ai.faq_matcher import FAQMatcher
from app.ai.feedback_analyzer import FeedbackAnalyzer
from app.database.repositories.feedback_repository import FeedbackRepository
from app.ai.message_classifier import classify_message
from app.database.repositories.message_repository import MessageRepository
from app.database.repositories.pending_ticket_repository import PendingTicketRepository
from app.utils.constants import MESSAGE_TYPE_FAQ


@dataclass(frozen=True)
class SupportResult:
    reply: str | None
    message_type: str
    matched_faq_id: int | None = None
    pending_ticket_id: int | None = None
    feedback_id: int | None = None


class SupportService:
    def __init__(
        self,
        db_path: str | Path | None = None,
        ai_client: AIClient | None = None,
        faq_match_threshold: float = 0.5,
    ) -> None:
        self.messages = MessageRepository(db_path)
        self.pending_tickets = PendingTicketRepository(db_path)
        self.feedback = FeedbackRepository(db_path)
        self.matcher = FAQMatcher(db_path)
        self.feedback_analyzer = FeedbackAnalyzer()
        self.chat_assistant = ChatAssistant(ai_client)
        self.faq_match_threshold = faq_match_threshold

    def process_player_message(
        self,
        message_id: int,
        discord_user_id: str,
        channel_id: str,
        content: str,
    ) -> SupportResult:
        message_type = classify_message(content)
        match = self.matcher.find_best_match(content, self.faq_match_threshold)
        feedback_id = self._create_feedback_if_needed(
            discord_user_id=discord_user_id,
            content=content,
            message_type=message_type,
        )

        if match:
            reply = self.chat_assistant.generate_faq_reply(content, match)
            self.messages.update_ai_reply(message_id, reply, MESSAGE_TYPE_FAQ)
            return SupportResult(
                reply=reply,
                message_type=MESSAGE_TYPE_FAQ,
                matched_faq_id=match.faq_id,
                feedback_id=feedback_id,
            )

        if _should_create_ticket(content, message_type):
            reply = self.chat_assistant.generate_unresolved_reply()
            ticket_id = self.pending_tickets.create(
                discord_user_id=discord_user_id,
                channel_id=channel_id,
                original_message=content,
                ticket_source="AI_DM_UNRESOLVED",
                issue_description="No confident FAQ match was found.",
            )
            self.messages.update_ai_reply(message_id, reply, message_type)
            return SupportResult(
                reply=reply,
                message_type=message_type,
                pending_ticket_id=ticket_id,
                feedback_id=feedback_id,
            )

        return SupportResult(reply=None, message_type=message_type, feedback_id=feedback_id)

    def _create_feedback_if_needed(
        self,
        discord_user_id: str,
        content: str,
        message_type: str,
    ) -> int | None:
        analysis = self.feedback_analyzer.analyze(content, message_type)
        if analysis is None:
            return None

        return self.feedback.create(
            discord_user_id=discord_user_id,
            content=content,
            category=analysis.category,
            feature=analysis.feature,
            keywords=", ".join(analysis.keywords),
            sentiment=analysis.sentiment,
            priority=analysis.priority,
        )


def _should_create_ticket(content: str, message_type: str) -> bool:
    if "?" in content:
        return True
    return message_type != "OTHER"
