from __future__ import annotations

from pathlib import Path

from app.dashboard.views.feedback_center import (
    _bulk_update_status,
    _collapse_thread_feedback,
    _consume_dialog_request,
    _feedback_history_html,
    _feedback_thread_title,
)
from app.database.migrations.init_db import init_database
from app.database.repositories.feedback_repository import FeedbackRepository


class FakeStreamlit:
    def __init__(self, session_state: dict) -> None:
        self.session_state = session_state


def test_feedback_detail_dialog_request_is_consumed_once() -> None:
    st = FakeStreamlit({"feedback_detail_id": 13})

    assert _consume_dialog_request(st, "feedback_detail_id") == 13
    assert _consume_dialog_request(st, "feedback_detail_id") is None


def test_feedback_calendar_dialog_request_is_consumed_once() -> None:
    st = FakeStreamlit({"feedback_calendar_open": True})

    assert _consume_dialog_request(st, "feedback_calendar_open") is True
    assert _consume_dialog_request(st, "feedback_calendar_open") is None


def test_feedback_queue_keeps_earliest_record_from_each_thread() -> None:
    records = [
        {"id": 3, "channel_name": "bug-report", "thread_title": "SSR rewards", "created_time": "2026-08-27 23:00:00"},
        {"id": 2, "channel_name": "bug-report", "thread_title": "SSR rewards", "created_time": "2026-08-27 22:00:00"},
        {"id": 1, "channel_name": "bug-report", "thread_title": "SSR rewards", "created_time": "2026-08-27 17:00:00"},
        {"id": 4, "channel_name": "bug-report", "thread_title": "Other issue", "created_time": "2026-08-28 01:00:00"},
    ]

    collapsed = _collapse_thread_feedback(records)

    assert [record["id"] for record in collapsed] == [1, 4]


def test_feedback_queue_uses_only_normalized_thread_title() -> None:
    record = {
        "thread_title": "  Translation   message expired  ",
        "content": "A much longer reply body that should stay in the detail view.",
    }

    assert _feedback_thread_title(record) == "Translation message expired"


def test_feedback_queue_labels_missing_thread_title_without_using_message_body() -> None:
    record = {"thread_title": None, "content": "Sensitive full message body"}

    assert _feedback_thread_title(record) == "未命名帖子"


def test_bulk_status_update_applies_to_all_records_in_thread(tmp_path: Path) -> None:
    db_path = tmp_path / "community.db"
    init_database(db_path)
    repository = FeedbackRepository(db_path)
    first_id = repository.create(
        "player-1",
        "Initial issue",
        "BUG",
        channel_name="bug-report",
        thread_title="SSR rewards",
    )
    repository.create(
        "player-2",
        "Follow-up reply",
        "BUG",
        channel_name="bug-report",
        thread_title="SSR rewards",
    )

    updated = _bulk_update_status(repository, [first_id], "Resolved")
    rows = repository.list_recent(10)

    assert updated == 1
    assert {row["status"] for row in rows} == {"Resolved"}


def test_feedback_history_html_renders_saved_reply_and_escapes_content() -> None:
    html = _feedback_history_html(
        [
            {
                "action_type": "BOT_REPLY",
                "content": "Checking <script>alert(1)</script>",
                "destination_label": "Bug <Report>",
                "discord_channel_id": "thread-1",
                "discord_message_id": "message-1",
                "created_time": "2026-09-08 12:34:00",
            }
        ]
    )

    assert "Bot 回复帖子" in html
    assert "2026/09/08 12:34" in html
    assert "Checking &lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "Bug &lt;Report&gt;" in html
    assert "message-1" in html
    assert "<script>" not in html


def test_feedback_history_html_has_clear_empty_state() -> None:
    html = _feedback_history_html([])

    assert "暂未产生处理记录" in html
    assert "Bot 回复帖子后会自动记录" in html
