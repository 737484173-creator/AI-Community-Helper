from __future__ import annotations

from pathlib import Path

import pytest

from app.bot.faq_flow import FAQFlowService
from app.database.migrations.init_db import init_database
from app.database.repositories.faq_repository import FAQRepository
from app.database.repositories.message_repository import MessageRepository
from app.database.repositories.pending_ticket_repository import PendingTicketRepository
from app.utils.constants import MESSAGE_TYPE_FAQ


def test_faq_flow_lists_categories_questions_and_answer(tmp_path: Path) -> None:
    db_path = tmp_path / "community.db"
    init_database(db_path)
    faq_repository = FAQRepository(db_path)
    faq_repository.upsert(
        category="Login",
        question="Cannot login",
        answer="Please restart the game.",
    )

    service = FAQFlowService(db_path)

    assert service.list_categories() == ["Login"]
    questions = service.list_questions("Login")
    assert len(questions) == 1
    assert questions[0].label == "Cannot login"

    answer = service.get_answer(questions[0].id)
    assert answer.category == "Login"
    assert answer.answer == "Please restart the game."


def test_faq_flow_marks_message_as_answered(tmp_path: Path) -> None:
    db_path = tmp_path / "community.db"
    init_database(db_path)
    FAQRepository(db_path).upsert(
        category="Login",
        question="Cannot login",
        answer="Please restart the game.",
    )
    message_id = MessageRepository(db_path).create(
        discord_user_id="discord-1",
        channel_id="channel-1",
        message="help",
    )

    service = FAQFlowService(db_path)
    answer = service.get_answer(service.list_questions("Login")[0].id)
    service.mark_message_answered(message_id, answer)

    message = MessageRepository(db_path).list_recent(1)[0]
    assert message["ai_reply"] == "Please restart the game."
    assert message["message_type"] == MESSAGE_TYPE_FAQ


def test_faq_flow_creates_pending_ticket_for_unresolved_issue(tmp_path: Path) -> None:
    db_path = tmp_path / "community.db"
    init_database(db_path)
    service = FAQFlowService(db_path)

    ticket_id = service.create_pending_ticket(
        discord_user_id="discord-1",
        channel_id="channel-1",
        original_message="help",
        selected_category="Login",
        selected_question="Cannot login",
        issue_description="Still cannot login after restart.",
    )

    ticket = PendingTicketRepository(db_path).list_open()[0]
    assert ticket["id"] == ticket_id
    assert ticket["selected_category"] == "Login"
    assert ticket["selected_question"] == "Cannot login"
    assert ticket["status"] == "Open"


def test_faq_flow_rejects_missing_answer(tmp_path: Path) -> None:
    db_path = tmp_path / "community.db"
    init_database(db_path)

    with pytest.raises(ValueError):
        FAQFlowService(db_path).get_answer(999)

