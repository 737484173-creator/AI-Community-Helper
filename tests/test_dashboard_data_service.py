from __future__ import annotations

from datetime import datetime
from pathlib import Path

from app.dashboard.data_service import DashboardDataService
from app.database.db import db_session
from app.database.migrations.init_db import init_database
from app.database.repositories.faq_repository import FAQRepository
from app.database.repositories.feedback_repository import FeedbackRepository
from app.database.repositories.message_repository import MessageRepository
from app.database.repositories.pending_ticket_repository import PendingTicketRepository


def test_dashboard_data_service_returns_today_metrics(tmp_path: Path) -> None:
    db_path = tmp_path / "community.db"
    init_database(db_path)
    MessageRepository(db_path).create(
        discord_user_id="discord-1",
        channel_id="channel-1",
        message="help",
        ai_reply="FAQ answer",
        message_type="FAQ",
    )
    MessageRepository(db_path).create(
        discord_user_id="discord-dm",
        channel_id="dm-1",
        message="private help",
        message_source="DM",
    )
    MessageRepository(db_path).create(
        discord_user_id="discord-risk",
        channel_id="channel-risk",
        message="you are an idiot",
    )
    FeedbackRepository(db_path).create(
        discord_user_id="discord-1",
        content="Crash on login",
        category="BUG",
        feature="Login",
        sentiment="Negative",
        priority="High",
    )
    PendingTicketRepository(db_path).create(
        discord_user_id="discord-1",
        channel_id="channel-1",
        original_message="Unknown issue",
    )
    PendingTicketRepository(db_path).create(
        discord_user_id="discord-2",
        channel_id="channel-2",
        original_message="Command issue",
        ticket_source="COMMAND_TICKET",
    )
    with db_session(db_path) as connection:
        connection.execute("UPDATE messages SET created_time = '2026-07-30 10:00:00'")
        connection.execute(
            "INSERT INTO discord_channels (channel_id, channel_name, channel_type, guild_id) "
            "VALUES ('channel-risk', 'game-chat', 'TextChannel', 'guild-1')"
        )
        connection.execute("UPDATE feedback SET created_time = '2026-07-30 10:00:00'")
        connection.execute(
            "UPDATE pending_tickets SET created_time = '2026-07-30 10:00:00'"
        )

    service = DashboardDataService(db_path)
    metrics = service.get_today_metrics(now=datetime(2026, 7, 30, 12, 0, 0))

    assert metrics.today_messages == 2
    assert metrics.today_ai_replies == 1
    assert metrics.today_feedback == 1
    assert metrics.today_high_risk_messages == 1
    assert metrics.open_pending_tickets == 1
    assert service.get_today_sentiment_counts(datetime(2026, 7, 30, 12, 0, 0)) == {
        "Negative": 1
    }
    assert service.get_today_feedback_categories(datetime(2026, 7, 30, 12, 0, 0)) == {
        "BUG": 1
    }


def test_dashboard_repositories_support_status_and_faq_updates(tmp_path: Path) -> None:
    db_path = tmp_path / "community.db"
    init_database(db_path)
    feedback = FeedbackRepository(db_path)
    feedback_id = feedback.create(
        discord_user_id="discord-1",
        content="Reward issue",
        category="REWARD_ISSUE",
    )
    ticket = PendingTicketRepository(db_path)
    ticket_id = ticket.create(
        discord_user_id="discord-1",
        channel_id="channel-1",
        original_message="Need help",
    )
    faq = FAQRepository(db_path)
    faq.upsert("Login", "Cannot login", "Restart.")
    faq_id = faq.list_all()[0]["id"]

    feedback.update_status(feedback_id, "Resolved")
    ticket.update_status(ticket_id, "Closed", "Operator A")
    faq.set_enabled(int(faq_id), False)

    assert feedback.list_recent(1)[0]["status"] == "Resolved"
    updated_ticket = ticket.list_recent(1)[0]
    assert updated_ticket["status"] == "Closed"
    assert updated_ticket["assigned_to"] == "Operator A"
    assert faq.count_all() == 1
    assert faq.list_all()[0]["enabled"] == 0
