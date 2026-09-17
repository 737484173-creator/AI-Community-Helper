from __future__ import annotations

from pathlib import Path

from app.database.migrations.init_db import init_database
from app.database.repositories.event_analytics_repository import (
    EventAnalyticsRepository,
)
from app.database.repositories.event_repository import EventRepository
from app.database.repositories.faq_repository import FAQRepository
from app.database.repositories.feedback_repository import FeedbackRepository
from app.database.repositories.message_repository import MessageRepository
from app.database.repositories.pending_ticket_repository import PendingTicketRepository
from app.database.repositories.report_repository import ReportRepository
from app.database.repositories.user_repository import UserRepository


def test_core_repositories_can_create_and_read_data(tmp_path: Path) -> None:
    db_path = tmp_path / "community_test.db"
    init_database(db_path)

    users = UserRepository(db_path)
    user = users.get_or_create("discord-1")
    assert user["discord_user_id"] == "discord-1"
    assert "player_id" in user.keys()
    assert "server_id" in user.keys()

    faqs = FAQRepository(db_path)
    faqs.upsert(
        category="Login",
        question="Cannot login",
        answer="Please restart the game and try again.",
        keywords="login,auth",
    )
    assert faqs.list_categories() == ["Login"]
    assert faqs.list_by_category("Login")[0]["answer"].startswith("Please")

    messages = MessageRepository(db_path)
    message_id = messages.create(
        discord_user_id="discord-1",
        channel_id="channel-1",
        message="I cannot login",
    )
    messages.update_ai_reply(message_id, "Please restart the game.", "FAQ")
    recent_message = messages.list_recent(1)[0]
    assert recent_message["ai_reply"] == "Please restart the game."
    assert recent_message["message_type"] == "FAQ"
    assert recent_message["message_source"] == "CHANNEL"

    messages.create(
        discord_user_id="discord-1",
        channel_id="dm-1",
        message="Private help",
        message_source="DM",
    )
    dm_messages = messages.list_between(
        "2000-01-01 00:00:00",
        "2099-01-01 00:00:00",
        message_source="DM",
    )
    assert len(dm_messages) == 1
    assert dm_messages[0]["message"] == "Private help"

    historical_id, historical_created = messages.create_if_new(
        discord_user_id="discord-1",
        channel_id="channel-1",
        message="Historical message",
        discord_message_id="history-1",
        created_time="2026-07-29 09:00:00",
    )
    duplicate_id, duplicate_created = messages.create_if_new(
        discord_user_id="discord-1",
        channel_id="channel-1",
        message="Historical message",
        discord_message_id="history-1",
        created_time="2026-07-29 10:00:00",
    )
    assert historical_created is True
    assert duplicate_created is False
    assert duplicate_id == historical_id
    assert messages.get_by_discord_message_id("history-1")["created_time"] == (
        "2026-07-29 10:00:00"
    )

    messages.create(
        discord_user_id="discord-1",
        channel_id="channel-1",
        message="Second public message",
        created_time="2026-07-29 18:00:00",
    )
    messages.create(
        discord_user_id="discord-1",
        channel_id="dm-1",
        message="Historical private message",
        message_source="DM",
        created_time="2026-07-29 19:00:00",
    )
    daily_counts = messages.count_channel_messages_by_day(
        "2026-07-29 00:00:00",
        "2026-07-30 23:59:59",
    )
    assert [dict(row) for row in daily_counts] == [
        {"message_date": "2026-07-29", "total": 2}
    ]

    feedback = FeedbackRepository(db_path)
    feedback.create(
        discord_user_id="discord-1",
        content="The reward is too low.",
        category="REWARD_ISSUE",
        feature="Reward",
        sentiment="Negative",
        priority="Medium",
    )
    assert feedback.list_open()[0]["category"] == "REWARD_ISSUE"

    tickets = PendingTicketRepository(db_path)
    tickets.create(
        discord_user_id="discord-1",
        channel_id="channel-1",
        original_message="Still not fixed",
        selected_category="Login",
        selected_question="Cannot login",
    )
    assert tickets.list_open()[0]["selected_category"] == "Login"

    events = EventRepository(db_path)
    event_id = events.create(
        title="Weekly Poll",
        content="Which mode do you like?",
        event_type="Poll",
        channel_id="channel-1",
        publish_time="2026-07-31 18:00:00",
        repeat_rule="weekly:friday:18:00",
        status="Scheduled",
    )
    assert events.list_scheduled()[0]["title"] == "Weekly Poll"
    events.update_status(event_id, "Published", "discord-message-1")

    analytics = EventAnalyticsRepository(db_path)
    analytics_id = analytics.create_initial(event_id, "2026-07-31 18:00:00")
    analytics.update_metrics(analytics_id, 12, 20, '{"A": 8, "B": 4}')

    reports = ReportRepository(db_path)
    reports.create(
        report_type="Daily",
        title="Daily Community Report",
        content="Reward complaints increased.",
        start_time="2026-07-30 00:00:00",
        end_time="2026-07-30 23:59:59",
    )
    assert reports.list_recent("Daily", 1)[0]["title"] == "Daily Community Report"
