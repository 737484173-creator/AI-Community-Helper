from __future__ import annotations

import inspect
from pathlib import Path
from types import SimpleNamespace

from app.dashboard.views.chat_monitor import _cached_channel_messages
from app.dashboard.views.feedback_center import (
    FEEDBACK_CACHE_REVISION_KEY,
    _clear_feedback_caches,
)
from app.dashboard.views.pending_issues import (
    PENDING_CACHE_REVISION_KEY,
    _clear_pending_caches,
)
from app.dashboard.views.reports import (
    REPORT_CACHE_REVISION_KEY,
    _cached_message_activity_rows,
    _clear_report_caches,
)


def _fake_streamlit() -> SimpleNamespace:
    return SimpleNamespace(session_state={})


def test_module_cache_revisions_are_independent() -> None:
    st = _fake_streamlit()

    _clear_feedback_caches(st)
    _clear_feedback_caches(st)
    _clear_pending_caches(st)
    _clear_report_caches(st)

    assert st.session_state[FEEDBACK_CACHE_REVISION_KEY] == 2
    assert st.session_state[PENDING_CACHE_REVISION_KEY] == 1
    assert st.session_state[REPORT_CACHE_REVISION_KEY] == 1


def test_hot_message_caches_do_not_use_whole_database_fingerprint() -> None:
    assert "file_fingerprint" not in inspect.getsource(_cached_channel_messages)
    assert "file_fingerprint" not in inspect.getsource(_cached_message_activity_rows)


def test_dashboard_views_do_not_clear_every_streamlit_cache() -> None:
    views_dir = Path(__file__).resolve().parents[1] / "app" / "dashboard" / "views"
    offenders = [
        path.name
        for path in views_dir.glob("*.py")
        if "st.cache_data.clear()" in path.read_text(encoding="utf-8")
    ]

    assert offenders == []
