from __future__ import annotations

import csv

import pytest

from app.database.migrations.init_db import init_database
from app.database.repositories.member_review_repository import MemberReviewRepository
from app.member_review.recheck import load_recheck_snapshot, recheck_snapshot_path


def _member_review_app(db_path: str) -> None:
    import streamlit as st

    from app.dashboard.views.member_review import render

    render(st, db_path)


def test_recheck_snapshot_is_indexed_by_application_id(tmp_path) -> None:
    db_path = tmp_path / "community.db"
    path = recheck_snapshot_path(db_path)
    path.parent.mkdir()
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=("申请ID", "复核分类", "Discord用户ID"))
        writer.writeheader()
        writer.writerow({"申请ID": 42, "复核分类": "旧区服误拒候选", "Discord用户ID": "123"})

    assert load_recheck_snapshot(path)[42]["复核分类"] == "旧区服误拒候选"


def test_recheck_snapshot_rejects_invalid_columns(tmp_path) -> None:
    path = tmp_path / "review.csv"
    path.write_text("申请ID,复核分类\n42,旧区服误拒候选\n", encoding="utf-8")

    with pytest.raises(ValueError, match="缺少必要字段"):
        load_recheck_snapshot(path)


def test_latest_application_is_separate_from_rejected_history(tmp_path) -> None:
    db_path = tmp_path / "community.db"
    init_database(db_path)
    repository = MemberReviewRepository(db_path)
    fields = dict(
        discord_username="player",
        discord_user_id="123",
        raw_application="S51 Player",
        player_name="Player",
        server_id="51",
        raw_server_input="S51",
        server_name="S51",
        discord_nickname="S51 Player",
        review_status="可通过",
        reason_code="PASS",
        internal_reason="Valid application",
        rejection_reason=None,
        confidence=1.0,
        auto_approvable=True,
    )
    old_id = repository.create_application(**fields)
    repository.update_review_result(
        application_id=old_id,
        review_status="已拒绝",
        final_result="拒绝",
        rejection_reason="Old rejection",
        nickname_result=None,
        discord_api_result="Rejected",
        reviewer="test",
    )
    new_id = repository.create_application(**fields)

    latest = repository.get_latest_by_discord_user_id("123")
    assert latest is not None
    assert latest["id"] == new_id
    assert latest["processed"] == 0
    assert repository.get(old_id)["review_status"] == "已拒绝"


def test_member_review_history_renders_without_actions(tmp_path) -> None:
    from streamlit.testing.v1 import AppTest

    db_path = tmp_path / "community.db"
    init_database(db_path)
    repository = MemberReviewRepository(db_path)
    application_id = repository.create_application(
        discord_username="player",
        discord_user_id="123",
        raw_application="S51 Player",
        player_name="Player",
        server_id="51",
        raw_server_input="S51",
        server_name="S51",
        discord_nickname="S51 Player",
        review_status="区服ID异常",
        reason_code="INVALID_SERVER_ID",
        internal_reason="Old server rule",
        rejection_reason="Old rejection",
        confidence=0.5,
        auto_approvable=False,
    )
    repository.update_review_result(
        application_id=application_id,
        review_status="已拒绝",
        final_result="拒绝",
        rejection_reason="Old rejection",
        nickname_result=None,
        discord_api_result="Rejected",
        reviewer="test",
    )
    path = recheck_snapshot_path(db_path)
    path.parent.mkdir()
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=("申请ID", "复核分类", "Discord用户ID", "现行规则状态"))
        writer.writeheader()
        writer.writerow({"申请ID": application_id, "复核分类": "旧区服误拒候选", "Discord用户ID": "123", "现行规则状态": "可通过"})

    app = AppTest.from_function(_member_review_app, args=(str(db_path),), default_timeout=15).run()
    assert not app.exception
    app.session_state["member_review_scope"] = "已拒绝名单（复核）"
    app.run()
    assert not app.exception
    assert len(app.dataframe) == 1
    assert not any(button.label in {"确认通过", "确认拒绝"} for button in app.button)


def test_rejected_detail_handles_stale_repository_class(tmp_path) -> None:
    from app.dashboard.views.member_review import _render_rejected_detail

    db_path = tmp_path / "community.db"
    init_database(db_path)
    repository = MemberReviewRepository(db_path)
    application_id = repository.create_application(
        discord_username="player",
        discord_user_id="123",
        raw_application="S51 Player",
        player_name="Player",
        server_id="51",
        raw_server_input="S51",
        server_name="S51",
        discord_nickname="S51 Player",
        review_status="已拒绝",
        reason_code="INVALID_SERVER_ID",
        internal_reason="Old server rule",
        rejection_reason="Old rejection",
        confidence=0.5,
        auto_approvable=False,
    )

    class LegacyRepository:
        _fetch_one = repository._fetch_one

    class CaptureStreamlit:
        def __init__(self) -> None:
            self.html = ""

        def markdown(self, html, **_kwargs) -> None:
            self.html += html

        def caption(self, _text) -> None:
            pass

    st = CaptureStreamlit()
    _render_rejected_detail(st, LegacyRepository(), repository.get(application_id), None)

    assert "尚无后续申请" in st.html
    assert "Old rejection" in st.html
