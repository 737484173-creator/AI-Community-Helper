from __future__ import annotations

from pathlib import Path

from app.bot.message_handler import IncomingDiscordMessage, MessageHandler
from app.database.migrations.init_db import init_database
from app.database.repositories.message_repository import MessageRepository
from app.database.repositories.user_repository import UserRepository
from app.utils.constants import MESSAGE_TYPE_OTHER


def test_message_handler_saves_user_and_message(tmp_path: Path) -> None:
    db_path = tmp_path / "community.db"
    init_database(db_path)

    handler = MessageHandler(db_path)
    result = handler.handle_incoming_message(
        IncomingDiscordMessage(
            discord_user_id="discord-123",
            channel_id="channel-456",
            content="hello support",
        )
    )

    assert result.message_type == MESSAGE_TYPE_OTHER

    user = UserRepository(db_path).get_by_discord_id("discord-123")
    assert user is not None
    assert user["player_id"] is None
    assert user["server_id"] is None

    message = MessageRepository(db_path).list_recent(1)[0]
    assert message["id"] == result.message_id
    assert message["discord_user_id"] == "discord-123"
    assert message["channel_id"] == "channel-456"
    assert message["message_source"] == "CHANNEL"
    assert message["message"] == "hello support"
    assert result.should_show_faq_flow is False


def test_message_handler_saves_dm_source(tmp_path: Path) -> None:
    db_path = tmp_path / "community.db"
    init_database(db_path)

    MessageHandler(db_path).handle_incoming_message(
        IncomingDiscordMessage(
            discord_user_id="discord-123",
            channel_id="dm-456",
            content="hello in dm",
            message_source="DM",
        )
    )

    message = MessageRepository(db_path).list_recent(1)[0]
    assert message["message_source"] == "DM"


def test_message_handler_shows_faq_flow_for_dm_help(tmp_path: Path) -> None:
    db_path = tmp_path / "community.db"
    init_database(db_path)

    result = MessageHandler(db_path).handle_incoming_message(
        IncomingDiscordMessage(
            discord_user_id="discord-123",
            channel_id="dm-456",
            content="help",
            message_source="DM",
        )
    )

    assert result.should_show_faq_flow is True


def test_message_handler_does_not_show_faq_for_regular_chat(tmp_path: Path) -> None:
    db_path = tmp_path / "community.db"
    init_database(db_path)

    result = MessageHandler(db_path).handle_incoming_message(
        IncomingDiscordMessage(
            discord_user_id="discord-123",
            channel_id="channel-456",
            content="I like this event",
        )
    )

    assert result.should_show_faq_flow is False


def test_message_handler_auto_replies_with_similar_faq(tmp_path: Path) -> None:
    db_path = tmp_path / "community.db"
    init_database(db_path)
    from app.database.repositories.faq_repository import FAQRepository

    FAQRepository(db_path).upsert(
        category="Payment",
        question="Payment Failed",
        answer="Please switch networks and log back into the game.",
        keywords="payment failed network",
    )

    result = MessageHandler(db_path).handle_incoming_message(
        IncomingDiscordMessage(
            discord_user_id="discord-123",
            channel_id="channel-456",
            content="payment failed",
            message_source="DM",
        )
    )

    assert result.should_show_faq_flow is False
    assert result.ai_reply == "Please switch networks and log back into the game."
    assert result.matched_faq_id is not None


def test_message_handler_does_not_auto_reply_in_public_channel(tmp_path: Path) -> None:
    db_path = tmp_path / "community.db"
    init_database(db_path)
    from app.database.repositories.faq_repository import FAQRepository

    FAQRepository(db_path).upsert(
        category="Payment",
        question="Payment Failed",
        answer="Please switch networks and log back into the game.",
        keywords="payment failed network",
    )

    result = MessageHandler(db_path).handle_incoming_message(
        IncomingDiscordMessage(
            discord_user_id="discord-123",
            channel_id="channel-456",
            content="payment failed",
            message_source="CHANNEL",
        )
    )

    assert result.should_show_faq_flow is False
    assert result.ai_reply is None
    assert result.matched_faq_id is None


def test_message_handler_skips_duplicate_discord_message_id(tmp_path: Path) -> None:
    db_path = tmp_path / "community.db"
    init_database(db_path)

    handler = MessageHandler(db_path)
    first = handler.handle_incoming_message(
        IncomingDiscordMessage(
            discord_user_id="discord-123",
            channel_id="channel-456",
            content="help",
            message_source="DM",
            discord_message_id="discord-message-1",
        )
    )
    second = handler.handle_incoming_message(
        IncomingDiscordMessage(
            discord_user_id="discord-123",
            channel_id="channel-456",
            content="help",
            message_source="DM",
            discord_message_id="discord-message-1",
        )
    )

    messages = MessageRepository(db_path).list_recent(10)
    assert len(messages) == 1
    assert first.message_id == second.message_id
    assert first.should_show_faq_flow is True
    assert second.should_show_faq_flow is False
    assert first.is_new_message is True
    assert second.is_new_message is False
