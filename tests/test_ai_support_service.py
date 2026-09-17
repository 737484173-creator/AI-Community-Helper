from __future__ import annotations

from pathlib import Path

from app.ai.message_classifier import classify_message
from app.ai.support_service import SupportService
from app.database.migrations.init_db import init_database
from app.database.repositories.faq_repository import FAQRepository
from app.database.repositories.feedback_repository import FeedbackRepository
from app.database.repositories.message_repository import MessageRepository
from app.database.repositories.pending_ticket_repository import PendingTicketRepository
from app.utils.constants import (
    FEEDBACK_CATEGORY_BUG,
    FEEDBACK_CATEGORY_REWARD_ISSUE,
    MESSAGE_TYPE_BUG,
    MESSAGE_TYPE_FAQ,
)


def test_support_service_replies_with_matched_faq(tmp_path: Path) -> None:
    db_path = tmp_path / "community.db"
    init_database(db_path)
    FAQRepository(db_path).upsert(
        category="Login",
        question="What should I do if I cannot login?",
        answer="Please check your network and restart the game.",
        keywords="login network restart",
    )
    message_id = MessageRepository(db_path).create(
        discord_user_id="discord-1",
        channel_id="channel-1",
        message="I cannot login because of network",
    )

    result = SupportService(db_path).process_player_message(
        message_id=message_id,
        discord_user_id="discord-1",
        channel_id="channel-1",
        content="I cannot login because of network",
    )

    assert result.message_type == MESSAGE_TYPE_FAQ
    assert result.reply == "Please check your network and restart the game."
    assert result.matched_faq_id is not None

    message = MessageRepository(db_path).list_recent(1)[0]
    assert message["ai_reply"] == result.reply
    assert message["message_type"] == MESSAGE_TYPE_FAQ


def test_support_service_creates_ticket_when_no_faq_match(tmp_path: Path) -> None:
    db_path = tmp_path / "community.db"
    init_database(db_path)
    message_id = MessageRepository(db_path).create(
        discord_user_id="discord-1",
        channel_id="channel-1",
        message="Why is my guild chest missing?",
    )

    result = SupportService(db_path).process_player_message(
        message_id=message_id,
        discord_user_id="discord-1",
        channel_id="channel-1",
        content="Why is my guild chest missing?",
    )

    assert result.reply is not None
    assert result.pending_ticket_id is not None
    ticket = PendingTicketRepository(db_path).list_open()[0]
    assert ticket["original_message"] == "Why is my guild chest missing?"
    assert ticket["issue_description"] == "No confident FAQ match was found."


def test_message_classifier_detects_bug() -> None:
    assert classify_message("The game crashes when I login") == MESSAGE_TYPE_BUG


def test_support_service_records_feedback_for_reward_complaint(tmp_path: Path) -> None:
    db_path = tmp_path / "community.db"
    init_database(db_path)
    message_id = MessageRepository(db_path).create(
        discord_user_id="discord-1",
        channel_id="channel-1",
        message="Dragon mine reward is too low and missing coins.",
    )

    result = SupportService(db_path).process_player_message(
        message_id=message_id,
        discord_user_id="discord-1",
        channel_id="channel-1",
        content="Dragon mine reward is too low and missing coins.",
    )

    assert result.feedback_id is not None
    feedback = FeedbackRepository(db_path).list_open()[0]
    assert feedback["category"] == FEEDBACK_CATEGORY_REWARD_ISSUE
    assert feedback["feature"] == "Reward"
    assert feedback["sentiment"] == "Negative"


def test_support_service_records_feedback_for_matched_bug_faq(tmp_path: Path) -> None:
    db_path = tmp_path / "community.db"
    init_database(db_path)
    FAQRepository(db_path).upsert(
        category="Login",
        question="What should I do if I cannot login?",
        answer="Please restart the game.",
        keywords="login",
    )
    message_id = MessageRepository(db_path).create(
        discord_user_id="discord-1",
        channel_id="channel-1",
        message="I cannot login",
    )

    result = SupportService(db_path).process_player_message(
        message_id=message_id,
        discord_user_id="discord-1",
        channel_id="channel-1",
        content="I cannot login",
    )

    assert result.matched_faq_id is not None
    assert result.feedback_id is not None
    feedback = FeedbackRepository(db_path).list_open()[0]
    assert feedback["category"] == FEEDBACK_CATEGORY_BUG
