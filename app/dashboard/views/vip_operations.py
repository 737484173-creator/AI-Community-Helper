from __future__ import annotations

from datetime import datetime
from html import escape
from io import BytesIO
from pathlib import Path

import pandas as pd

from app.database.repositories.vip_ae_repository import AEVIPSnapshotRepository
from app.dashboard.design_tokens import COLORS
from app.dashboard.views.vip_common import (
    compact_multiselect_filter,
    section,
)
from app.vip.ae_sync import AEVIPSyncError, AEVIPSyncService, DEFAULT_AE_PROJECT_ID
from app.vip.server_merges import server_merge_summary
from app.vip.service import (
    CONTACT_PRIORITIES,
    DEFAULT_VIP_FILE,
    HIDDEN_DETAIL_COLUMNS,
    RETIREMENT_INACTIVITY_DAYS,
    contact_count_for_group,
    dataframe_to_excel_bytes,
    filter_options,
    load_ae_vip_workbook,
    load_vip_workbook,
    server_contact_counts,
    vip_summary_metrics,
)


VIP_WORKBOOK_CACHE_VERSION = "vip-rules-2026-09-10-v3"

def _load_uploaded_workbook(st, file_name: str, file_bytes: bytes):
    @st.cache_data(show_spinner=False)
    def _cached_uploaded_workbook(name: str, payload: bytes):
        source = BytesIO(payload)
        source.name = name
        return load_vip_workbook(source)

    return _cached_uploaded_workbook(file_name, file_bytes)


def _load_default_workbook(st, path: str, fingerprint: tuple[int, int]):
    @st.cache_data(show_spinner=False)
    def _cached_default_workbook(file_path: str, source_fingerprint: tuple[int, int], rules_version: str):
        return load_vip_workbook(DEFAULT_VIP_FILE.__class__(file_path))

    return _cached_default_workbook(path, fingerprint, VIP_WORKBOOK_CACHE_VERSION)


def _load_ae_workbook(st, db_path: str, snapshot_revision: tuple[int, str]):
    @st.cache_data(show_spinner=False)
    def _cached_ae_workbook(path: str, source_revision: tuple[int, str], rules_version: str):
        return load_ae_vip_workbook(Path(path), DEFAULT_AE_PROJECT_ID)

    return _cached_ae_workbook(db_path, snapshot_revision, VIP_WORKBOOK_CACHE_VERSION)


def _file_fingerprint(path: str | Path) -> tuple[int, int]:
    try:
        stat = Path(path).stat()
    except FileNotFoundError:
        return (0, 0)
    return int(stat.st_mtime_ns), int(stat.st_size)


def _ae_snapshot_state(db_path) -> tuple[int, object | None, object | None]:
    if db_path is None:
        return 0, None, None
    try:
        repository = AEVIPSnapshotRepository(db_path)
        summary = repository.get_snapshot_summary(DEFAULT_AE_PROJECT_ID)
        latest_run = repository.get_latest_run(DEFAULT_AE_PROJECT_ID)
        count = int(summary["row_count"]) if summary else 0
        synced_at = summary["synced_at"] if summary else None
        return count, synced_at, latest_run
    except Exception:
        return 0, None, None


def load_current_workbook(st, db_path=None):
    file_bytes = st.session_state.get("vip_uploaded_bytes")
    file_name = st.session_state.get("vip_uploaded_name")
    if file_bytes and file_name:
        return _load_uploaded_workbook(st, str(file_name), bytes(file_bytes))
    snapshot_count, snapshot_synced_at, _ = _ae_snapshot_state(db_path)
    if snapshot_count:
        snapshot_revision = (snapshot_count, str(snapshot_synced_at or ""))
        return _load_ae_workbook(st, str(db_path), snapshot_revision)
    if DEFAULT_VIP_FILE.exists():
        stat = DEFAULT_VIP_FILE.stat()
        return _load_default_workbook(
            st,
            str(DEFAULT_VIP_FILE),
            (int(stat.st_mtime_ns), int(stat.st_size)),
        )
    return None


UPLOAD_STATE_KEYS = (
    "vip_uploaded_name",
    "vip_uploaded_bytes",
    "vip_uploaded_size",
    "vip_uploaded_time",
)


def _vip_overview_css(st) -> None:
    st.markdown(
        """
        <style>
        .vip-metric-band {
            display: grid;
            gap: 0;
            overflow: hidden;
            border-top: 1px solid var(--border-strong);
            border-bottom: 1px solid var(--border);
            background: color-mix(in srgb, var(--surface) 56%, transparent);
            animation: content-enter var(--motion-enter) var(--ease-standard) both;
            transform: translateY(0);
            transition:
                transform var(--motion-standard) var(--ease-standard),
                border-color var(--motion-standard) var(--ease-standard),
                background-color var(--motion-standard) var(--ease-standard),
                box-shadow var(--motion-standard) var(--ease-standard);
        }
        .vip-metric-band:hover {
            z-index: 1;
            transform: translateY(-2px);
            border-color: color-mix(in srgb, var(--primary) 22%, var(--border));
            background: color-mix(in srgb, var(--primary-soft) 16%, var(--surface));
            box-shadow: var(--shadow-2);
        }
        .vip-metric-band.primary { grid-template-columns: repeat(5, minmax(0, 1fr)); }
        .vip-metric-band.secondary {
            grid-template-columns: repeat(4, minmax(0, 1fr));
            margin: 10px 0 24px;
        }
        .vip-metric-item {
            position: relative;
            min-width: 0;
            min-height: 112px;
            padding: 18px 18px 16px;
            background: transparent;
            transition:
                background-color var(--motion-standard) var(--ease-standard),
                box-shadow var(--motion-standard) var(--ease-standard);
        }
        .vip-metric-item:hover {
            background: color-mix(in srgb, var(--primary-soft) 44%, transparent);
            box-shadow: inset 0 -2px 0 color-mix(in srgb, var(--primary) 58%, transparent);
        }
        .vip-metric-item + .vip-metric-item { border-left: 1px solid var(--border); }
        .vip-metric-item.attention { background: color-mix(in srgb, var(--primary-soft) 24%, transparent); }
        .vip-metric-label {
            color: var(--text-secondary);
            font-size: 12px;
            font-weight: 630;
            line-height: 18px;
            text-wrap: pretty;
        }
        .vip-metric-value {
            display: inline-block;
            margin: 6px 0 7px;
            color: var(--text-primary);
            font-size: clamp(30px, 3vw, 38px);
            font-weight: 720;
            font-variant-numeric: tabular-nums;
            line-height: 1;
            letter-spacing: -.045em;
            transform-origin: left center;
            transition:
                transform var(--motion-standard) var(--ease-standard),
                color var(--motion-standard) var(--ease-standard);
        }
        .vip-metric-item:hover .vip-metric-value {
            color: var(--primary-hover);
            transform: translateY(-1px) scale(1.025);
        }
        .vip-metric-item.attention .vip-metric-value { color: var(--primary); }
        .vip-metric-note {
            color: var(--text-tertiary);
            font-size: 12px;
            line-height: 17px;
            text-wrap: pretty;
        }
        .vip-file-status-card {
            position: relative;
            overflow: hidden;
            transform: translateY(0);
            transition:
                transform var(--motion-standard) var(--ease-standard),
                border-color var(--motion-standard) var(--ease-standard),
                background-color var(--motion-standard) var(--ease-standard),
                box-shadow var(--motion-standard) var(--ease-standard);
        }
        .vip-file-status-card::after {
            position: absolute;
            right: 16px;
            bottom: 0;
            width: 38px;
            height: 2px;
            border-radius: 2px 2px 0 0;
            background: var(--primary);
            content: "";
            opacity: .55;
            transform-origin: right center;
            transition:
                width var(--motion-standard) var(--ease-standard),
                opacity var(--motion-fast) var(--ease-standard);
        }
        .vip-file-status-card:hover {
            transform: translateY(-2px);
            border-color: color-mix(in srgb, var(--primary) 24%, var(--border)) !important;
            background: color-mix(in srgb, var(--primary-soft) 16%, var(--surface)) !important;
            box-shadow: var(--shadow-2) !important;
        }
        .vip-file-status-card:hover::after {
            width: 88px;
            opacity: 1;
        }
        .vip-file-status-card .event-effect-title,
        .vip-file-status-card .status-pill {
            transition:
                color var(--motion-standard) var(--ease-standard),
                border-color var(--motion-standard) var(--ease-standard),
                background-color var(--motion-standard) var(--ease-standard);
        }
        .vip-file-status-card:hover .event-effect-title { color: var(--primary-hover); }
        .vip-file-status-card:hover .status-pill {
            border-color: color-mix(in srgb, var(--primary) 22%, var(--border));
            background: color-mix(in srgb, var(--primary-soft) 38%, var(--surface-muted));
        }
        .st-key-vip_insight_ranking,
        .st-key-vip_insight_servers {
            min-height: 100%;
            padding: 0;
            background: transparent;
        }
        [class*="st-key-vip_contact_insight_drawer"] {
            margin-top: 8px;
        }
        [class*="st-key-vip_contact_insight_drawer"] details {
            overflow: hidden;
            border: 1px solid var(--border-strong) !important;
            border-radius: var(--radius-panel) !important;
            background: color-mix(in srgb, var(--surface) 94%, var(--primary-soft)) !important;
            box-shadow: var(--shadow-1);
            transition:
                border-color var(--motion-standard) var(--ease-standard),
                box-shadow var(--motion-standard) var(--ease-standard),
                background-color var(--motion-standard) var(--ease-standard);
        }
        [class*="st-key-vip_contact_insight_drawer"] details:hover {
            border-color: color-mix(in srgb, var(--primary) 30%, var(--border-strong)) !important;
            box-shadow: var(--shadow-2);
        }
        [class*="st-key-vip_contact_insight_drawer"] details summary {
            min-height: 54px;
            padding: 0 18px !important;
            color: var(--text-primary);
            font-weight: 680;
            transition:
                color var(--motion-standard) var(--ease-standard),
                background-color var(--motion-standard) var(--ease-standard);
        }
        [class*="st-key-vip_contact_insight_drawer"] details summary:hover {
            color: var(--primary-hover);
            background: color-mix(in srgb, var(--primary-soft) 36%, transparent);
        }
        [class*="st-key-vip_contact_insight_drawer"] details[open] summary {
            border-bottom: 1px solid var(--border);
        }
        [class*="st-key-vip_contact_insight_drawer"] details > div {
            padding: 12px 16px 16px !important;
        }
        [class*="st-key-vip_contact_insight_drawer"] details[open] > div {
            animation: vip-drawer-reveal 560ms var(--ease-standard) both;
        }
        .vip-insight-summary {
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            margin: 2px 0 14px;
            overflow: hidden;
            border: 1px solid var(--border);
            border-radius: var(--radius-card);
            background: var(--surface-muted);
        }
        .vip-insight-summary-item {
            min-width: 0;
            padding: 11px 14px;
            border-left: 1px solid var(--border);
            transition:
                transform 360ms var(--ease-standard),
                background-color 360ms var(--ease-standard);
        }
        .vip-insight-summary-item:first-child { border-left: 0; }
        .vip-insight-summary-item:hover {
            z-index: 1;
            transform: translateY(-1px);
            background: color-mix(in srgb, var(--primary-soft) 48%, var(--surface));
        }
        .vip-insight-summary-item span {
            display: block;
            color: var(--text-tertiary);
            font-size: 11px;
            line-height: 16px;
        }
        .vip-insight-summary-item strong {
            display: block;
            margin-top: 2px;
            color: var(--text-primary);
            font-size: 17px;
            font-weight: 720;
            line-height: 22px;
            text-wrap: pretty;
        }
        .vip-insight-summary-item.attention strong { color: var(--danger); }
        .vip-ranking-panel {
            min-height: 100%;
            overflow: hidden;
            border: 1px solid var(--border);
            border-radius: var(--radius-card);
            background: var(--surface);
            box-shadow: 0 1px 2px rgba(16, 24, 40, 0.025);
            transition:
                transform 420ms var(--ease-standard),
                border-color 420ms var(--ease-standard),
                box-shadow 420ms var(--ease-standard);
        }
        .vip-ranking-panel:hover {
            transform: translateY(-2px);
            border-color: color-mix(in srgb, var(--primary) 24%, var(--border));
            box-shadow: var(--shadow-1);
        }
        .vip-ranking-panel-header {
            display: flex;
            align-items: flex-start;
            justify-content: space-between;
            gap: 12px;
            min-height: 64px;
            padding: 14px 16px 12px;
            border-bottom: 1px solid var(--border);
        }
        .vip-ranking-panel-title {
            color: var(--text-primary);
            font-size: 14px;
            font-weight: 720;
            line-height: 20px;
        }
        .vip-ranking-panel-copy {
            margin-top: 2px;
            color: var(--text-tertiary);
            font-size: 11px;
            line-height: 17px;
            text-wrap: pretty;
        }
        .vip-ranking-panel-count {
            flex: 0 0 auto;
            padding: 4px 9px;
            border: 1px solid color-mix(in srgb, var(--primary) 18%, var(--border));
            border-radius: var(--radius-pill);
            background: var(--primary-soft);
            color: var(--primary-hover);
            font-size: 11px;
            font-weight: 680;
            white-space: nowrap;
        }
        .vip-ranking-table-head,
        .vip-ranking-row {
            display: grid;
            grid-template-columns: 34px minmax(112px, 1fr) 72px 92px 48px;
            align-items: center;
            column-gap: 8px;
        }
        .vip-ranking-table-head {
            min-height: 34px;
            padding: 0 12px;
            background: var(--surface-muted);
            color: var(--text-tertiary);
            font-size: 10px;
            font-weight: 650;
        }
        .vip-ranking-table-head span:last-child { text-align: right; }
        .vip-ranking-list {
            max-height: 500px;
            padding-bottom: 8px;
            overflow-y: auto;
            overscroll-behavior: contain;
            scroll-padding-block-end: 72px;
            scrollbar-width: none;
            -ms-overflow-style: none;
        }
        .vip-ranking-list::-webkit-scrollbar {
            display: none;
            width: 0;
            height: 0;
        }
        [class*="st-key-vip_contact_insight_drawer"] .vip-ranking-entry {
            display: block;
            overflow: visible;
            border: 0 !important;
            border-radius: 0 !important;
            background: transparent !important;
            box-shadow: none !important;
        }
        [class*="st-key-vip_contact_insight_drawer"] .vip-ranking-entry:hover {
            border-color: transparent !important;
            box-shadow: none !important;
        }
        [class*="st-key-vip_contact_insight_drawer"] .vip-ranking-entry > summary.vip-ranking-row {
            min-height: 45px;
            padding: 0 12px !important;
            color: inherit;
            cursor: pointer;
            list-style: none;
        }
        .vip-ranking-entry > summary::-webkit-details-marker { display: none; }
        [class*="st-key-vip_contact_insight_drawer"] .vip-ranking-entry[open] > summary.vip-ranking-row {
            border-bottom: 0;
            background: color-mix(in srgb, var(--primary-soft) 58%, var(--surface));
            box-shadow: -3px 0 0 var(--primary);
        }
        .vip-ranking-row {
            position: relative;
            min-height: 45px;
            padding: 0 12px;
            border-top: 1px solid color-mix(in srgb, var(--border) 74%, transparent);
            animation: vip-ranking-row-enter 520ms var(--ease-standard) backwards;
            animation-delay: calc(var(--row-index) * 34ms);
            transition:
                transform 360ms var(--ease-standard),
                background-color 360ms var(--ease-standard),
                box-shadow 360ms var(--ease-standard);
        }
        .vip-ranking-row:first-child { border-top: 0; }
        .vip-ranking-row:hover {
            z-index: 2;
            transform: translateX(3px);
            background: color-mix(in srgb, var(--primary-soft) 46%, var(--surface));
            box-shadow: -3px 0 0 var(--primary);
        }
        .vip-ranking-row.top-three {
            background: color-mix(in srgb, var(--warning) 4%, var(--surface));
        }
        .vip-rank-number {
            color: var(--text-tertiary);
            font-size: 11px;
            font-variant-numeric: tabular-nums;
        }
        .vip-ranking-row.top-three .vip-rank-number {
            color: var(--primary-hover);
            font-weight: 720;
        }
        .vip-rank-player {
            min-width: 0;
            line-height: 16px;
        }
        .vip-rank-player strong {
            display: flex;
            align-items: center;
            gap: 5px;
            overflow: hidden;
            color: var(--text-primary);
            font-size: 12px;
            font-weight: 660;
            text-overflow: ellipsis;
            white-space: nowrap;
        }
        .vip-player-hint {
            display: inline-flex !important;
            flex: 0 0 auto;
            align-items: center;
            color: var(--primary-hover) !important;
            font-size: 9px !important;
            font-style: normal;
            font-weight: 650;
            opacity: 0;
            transform: translateX(-3px);
            transition: opacity 300ms var(--ease-standard), transform 300ms var(--ease-standard);
        }
        .vip-ranking-row:hover .vip-player-hint,
        .vip-ranking-entry[open] .vip-player-hint {
            opacity: 1;
            transform: translateX(0);
        }
        [class*="st-key-vip_contact_insight_drawer"] .vip-ranking-entry > .vip-player-detail {
            display: grid;
            grid-template-columns: minmax(120px, 1.2fr) repeat(2, minmax(72px, .72fr)) minmax(100px, 1fr);
            gap: 8px;
            padding: 10px 12px 12px 54px !important;
            border-top: 1px dashed color-mix(in srgb, var(--primary) 18%, var(--border));
            background: color-mix(in srgb, var(--primary-soft) 25%, var(--surface));
            animation: vip-player-detail-reveal 420ms var(--ease-standard) both;
        }
        .vip-player-detail-item {
            min-width: 0;
            color: var(--text-secondary);
            font-size: 10px;
            line-height: 16px;
        }
        .vip-player-detail-item span {
            display: block;
            color: var(--text-tertiary);
            font-size: 9px;
        }
        .vip-player-detail-item strong,
        .vip-player-detail-item code {
            display: block;
            overflow: hidden;
            color: var(--text-primary);
            font-family: inherit;
            font-size: 11px;
            font-weight: 650;
            text-overflow: ellipsis;
            white-space: nowrap;
            user-select: text;
        }
        .vip-player-detail-item code {
            width: fit-content;
            padding: 1px 5px;
            border: 1px solid color-mix(in srgb, var(--primary) 16%, var(--border));
            border-radius: 5px;
            background: var(--surface);
            color: var(--primary-hover);
        }
        .vip-rank-player span {
            display: block;
            overflow: hidden;
            color: var(--text-tertiary);
            font-size: 10px;
            text-overflow: ellipsis;
            white-space: nowrap;
        }
        .vip-priority-chip {
            justify-self: start;
            padding: 3px 7px;
            border-radius: var(--radius-pill);
            font-size: 10px;
            font-weight: 680;
            white-space: nowrap;
        }
        .vip-priority-chip.immediate {
            background: color-mix(in srgb, var(--danger) 10%, var(--surface));
            color: var(--danger);
        }
        .vip-priority-chip.priority {
            background: color-mix(in srgb, var(--warning) 10%, var(--surface));
            color: var(--warning);
        }
        .vip-score-pair {
            display: flex;
            align-items: center;
            gap: 7px;
            color: var(--text-secondary);
            font-size: 10px;
            font-variant-numeric: tabular-nums;
            white-space: nowrap;
        }
        .vip-score-pair b { color: var(--text-primary); font-weight: 680; }
        .vip-composite-score {
            justify-self: end;
            color: var(--text-primary);
            font-size: 13px;
            font-weight: 760;
            font-variant-numeric: tabular-nums;
        }
        .vip-ranking-progress {
            position: absolute;
            inset: auto 0 0;
            height: 2px;
            overflow: hidden;
            background: transparent;
        }
        .vip-ranking-progress span {
            display: block;
            width: var(--bar-width);
            height: 100%;
            transform-origin: left center;
            background: var(--primary);
            opacity: 0.64;
            animation: vip-ranking-bar-grow 820ms var(--ease-standard) both;
            animation-delay: calc(120ms + var(--row-index) * 34ms);
        }
        .vip-ranking-row.immediate .vip-ranking-progress span { background: var(--danger); }
        .vip-ranking-row.priority .vip-ranking-progress span { background: var(--warning); }
        .vip-server-table-head,
        .vip-server-row {
            display: grid;
            grid-template-columns: 34px 48px minmax(100px, 1fr) 38px;
            align-items: center;
            column-gap: 8px;
        }
        .vip-server-table-head {
            min-height: 34px;
            padding: 0 12px;
            background: var(--surface-muted);
            color: var(--text-tertiary);
            font-size: 10px;
            font-weight: 650;
        }
        .vip-server-table-head span:last-child { text-align: right; }
        .vip-server-list { min-height: 500px; }
        .vip-server-row {
            min-height: 41px;
            padding: 0 12px;
            border-top: 1px solid color-mix(in srgb, var(--border) 74%, transparent);
            animation: vip-ranking-row-enter 520ms var(--ease-standard) backwards;
            animation-delay: calc(var(--row-index) * 42ms);
            transition:
                transform 360ms var(--ease-standard),
                background-color 360ms var(--ease-standard);
        }
        .vip-server-row:hover {
            transform: translateX(3px);
            background: color-mix(in srgb, var(--primary-soft) 54%, var(--surface));
        }
        .vip-server-rank {
            color: var(--text-tertiary);
            font-size: 11px;
            font-variant-numeric: tabular-nums;
        }
        .vip-server-row.top-three .vip-server-rank,
        .vip-server-row.top-three .vip-server-name {
            color: var(--primary-hover);
            font-weight: 720;
        }
        .vip-server-name {
            color: var(--text-primary);
            font-size: 12px;
            font-weight: 650;
        }
        .vip-server-track {
            height: 8px;
            overflow: hidden;
            border-radius: var(--radius-pill);
            background: var(--surface-muted);
        }
        .vip-server-track span {
            display: block;
            width: var(--bar-width);
            height: 100%;
            border-radius: inherit;
            background: var(--risk-low);
            animation: vip-ranking-bar-grow 840ms var(--ease-standard) both;
            animation-delay: calc(140ms + var(--row-index) * 42ms);
        }
        .vip-server-row.top-three .vip-server-track span { background: var(--primary); }
        .vip-server-count {
            justify-self: end;
            color: var(--text-primary);
            font-size: 12px;
            font-weight: 720;
            font-variant-numeric: tabular-nums;
        }
        .vip-ranking-empty {
            display: grid;
            min-height: 180px;
            place-items: center;
            padding: 24px;
            color: var(--text-tertiary);
            font-size: 12px;
            text-align: center;
        }
        @keyframes vip-drawer-reveal {
            from { opacity: 0; transform: translateY(-8px); }
            to { opacity: 1; transform: translateY(0); }
        }
        @keyframes vip-ranking-row-enter {
            from { opacity: 0; transform: translateY(7px); }
            to { opacity: 1; transform: translateY(0); }
        }
        @keyframes vip-ranking-bar-grow {
            from { width: 0; }
            to { width: var(--bar-width); }
        }
        @keyframes vip-player-detail-reveal {
            from { opacity: 0; transform: translateY(-5px); }
            to { opacity: 1; transform: translateY(0); }
        }
        .st-key-vip_player_export {
            margin-top: 6px;
            padding: 14px 16px;
            border-top: 1px solid var(--border-strong);
            border-bottom: 1px solid var(--border);
            background: color-mix(in srgb, var(--surface) 52%, transparent);
        }
        @media (max-width: 980px) {
            .vip-metric-band.primary { grid-template-columns: repeat(3, minmax(0, 1fr)); }
            .vip-metric-band.primary .vip-metric-item:nth-child(4) { border-left: 0; }
            .vip-metric-band.primary .vip-metric-item:nth-child(n+4) { border-top: 1px solid var(--border); }
        }
        @media (max-width: 640px) {
            .vip-metric-band.primary,
            .vip-metric-band.secondary { grid-template-columns: repeat(2, minmax(0, 1fr)); }
            .vip-metric-item { min-height: 98px; padding: 14px 12px; }
            .vip-metric-band .vip-metric-item:nth-child(odd) { border-left: 0; }
            .vip-metric-band .vip-metric-item:nth-child(n+3) { border-top: 1px solid var(--border); }
            .vip-metric-band .vip-metric-item:last-child:nth-child(odd) { grid-column: 1 / -1; }
        }
        @media (prefers-reduced-motion: reduce) {
            .vip-metric-band,
            .vip-metric-item,
            .vip-metric-value,
            .vip-file-status-card,
            .vip-file-status-card::after,
            .vip-file-status-card .event-effect-title,
            .vip-file-status-card .status-pill,
            .st-key-vip_insight_ranking,
            .st-key-vip_insight_servers,
            [class*="st-key-vip_contact_insight_drawer"] details[open] > div,
            .vip-insight-summary-item,
            .vip-ranking-panel,
            .vip-ranking-row,
            .vip-player-hint,
            .vip-player-detail,
            .vip-ranking-progress span,
            .vip-server-row,
            .vip-server-track span {
                animation: none !important;
                transition: none !important;
            }
            .vip-metric-band:hover,
            .vip-metric-item:hover .vip-metric-value,
            .vip-file-status-card:hover,
            .vip-insight-summary-item:hover,
            .vip-ranking-panel:hover,
            .vip-ranking-row:hover,
            .vip-server-row:hover {
                transform: none !important;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _vip_metric_item(label: str, value: int | float | str, note: str, tone: str = "") -> str:
    tone_class = f" {escape(tone)}" if tone else ""
    return (
        f'<div class="vip-metric-item{tone_class}">'
        f'<div class="vip-metric-label">{escape(label)}</div>'
        f'<div class="vip-metric-value">{escape(str(value))}</div>'
        f'<div class="vip-metric-note">{escape(note)}</div>'
        "</div>"
    )


def _render_vip_metric_band(st, items: list[tuple[str, int | float | str, str, str]], variant: str) -> None:
    st.markdown(
        f'<div class="vip-metric-band {escape(variant)}">'
        + "".join(_vip_metric_item(label, value, note, tone) for label, value, note, tone in items)
        + "</div>",
        unsafe_allow_html=True,
    )


def _remember_uploaded_file(uploaded_file: object, st) -> None:
    st.session_state.vip_uploaded_name = uploaded_file.name
    st.session_state.vip_uploaded_bytes = uploaded_file.getvalue()
    st.session_state.vip_uploaded_size = uploaded_file.size
    st.session_state.vip_uploaded_time = datetime.now().strftime("%Y-%m-%d %H:%M")


def _clear_uploaded_file(st) -> None:
    for key in UPLOAD_STATE_KEYS:
        st.session_state.pop(key, None)


def _uploaded_source_from_state(st) -> BytesIO | None:
    file_bytes = st.session_state.get("vip_uploaded_bytes")
    file_name = st.session_state.get("vip_uploaded_name")
    if not file_bytes or not file_name:
        return None
    source = BytesIO(file_bytes)
    source.name = str(file_name)
    return source


def _current_source(st, db_path=None):
    uploaded_source = _uploaded_source_from_state(st)
    if uploaded_source is not None:
        return uploaded_source
    snapshot_count, _, _ = _ae_snapshot_state(db_path)
    if snapshot_count:
        return "ae_snapshot"
    return DEFAULT_VIP_FILE if DEFAULT_VIP_FILE.exists() else None


def _format_file_size(size_bytes: int) -> str:
    if size_bytes >= 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.2f} MB"
    if size_bytes >= 1024:
        return f"{size_bytes / 1024:.1f} KB"
    return f"{size_bytes} B"


def _render_data_source(st, db_path) -> None:
    section(
        st,
        "数据源",
        "默认读取 AE 项目 24 的最新快照；上传 Excel 后将临时覆盖 AE 数据。",
        "upload",
    )
    snapshot_count, snapshot_synced_at, latest_run = _ae_snapshot_state(db_path)
    upload_cols = st.columns(2)
    with upload_cols[0]:
        if st.button("从 AE 同步最新数据", type="primary", use_container_width=True):
            try:
                with st.spinner("正在从 AE 项目 24 同步 VIP 数据…"):
                    result = AEVIPSyncService(db_path).sync()
                snapshot_count = result.vip_row_count
                snapshot_synced_at = result.synced_at
                latest_run = AEVIPSnapshotRepository(db_path).get_latest_run(DEFAULT_AE_PROJECT_ID)
                st.success(
                    f"同步完成：{result.vip_row_count} 名 VIP；近七日窗口 {result.weekly_window}；"
                    f"前七日对比 {result.previous_week_window}；28 日基准 {result.rolling_28d_window}。"
                )
            except AEVIPSyncError as exc:
                st.error(f"AE 同步失败：{exc}")
        uploaded_file = st.file_uploader(
            "上传 VIP Excel（手动覆盖/故障回退）",
            type=["xlsx"],
            key=f"vip_excel_upload_{st.session_state.get('vip_upload_widget_version', 0)}",
        )
        if uploaded_file is not None:
            _remember_uploaded_file(uploaded_file, st)
    with upload_cols[1]:
        if st.session_state.get("vip_uploaded_name"):
            file_name = str(st.session_state.vip_uploaded_name)
            file_size = _format_file_size(int(st.session_state.vip_uploaded_size))
            upload_time = str(st.session_state.vip_uploaded_time)
            status = "上传文件"
        elif snapshot_count:
            file_name = "AE 项目 24 · 巨兽战场-正式-全球"
            file_size = f"{snapshot_count:,} 名 VIP"
            upload_time = str(snapshot_synced_at or "-").replace("T", " ").replace("+00:00", " UTC")
            status = "AE 快照"
        elif DEFAULT_VIP_FILE.exists():
            file_name = DEFAULT_VIP_FILE.name
            file_size = _format_file_size(DEFAULT_VIP_FILE.stat().st_size)
            upload_time = datetime.fromtimestamp(DEFAULT_VIP_FILE.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
            status = "默认文件"
        else:
            file_name = "暂无文件"
            file_size = "-"
            upload_time = "-"
            status = "等待上传"
        st.markdown(
            f"""
            <div class="event-effect-card vip-file-status-card">
                <div class="event-effect-title">当前数据源</div>
                <div class="status-row">
                    <span class="status-pill info">状态：{status}</span>
                    <span class="status-pill neutral">大小：{file_size}</span>
                    <span class="status-pill neutral">时间：{upload_time}</span>
                </div>
                <div class="report-preview-meta">{file_name}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if st.session_state.get("vip_uploaded_name") and st.button("删除上传文件", use_container_width=True):
            _clear_uploaded_file(st)
            st.session_state.vip_upload_widget_version = st.session_state.get("vip_upload_widget_version", 0) + 1
            st.rerun()
        if latest_run is not None and latest_run["status"] == "FAILED":
            st.warning(
                "最近一次 AE 刷新失败，页面继续使用上一版成功快照："
                + str(latest_run["error_message"] or "未知错误")
            )


def _filter_dataframe(st, scored_df: pd.DataFrame) -> pd.DataFrame:
    with st.container(key="vip_filter_drawer_operations"):
        with st.expander("查看与调整筛选", expanded=False):
            group_options = filter_options(scored_df, "玩家分组")
            server_options = filter_options(scored_df, "区服")
            source_options = filter_options(scored_df, "用户来源")
            priority_options = filter_options(scored_df, "触达优先级")
            filter_cols = st.columns(4)
            selected_group = compact_multiselect_filter(
                st,
                filter_cols[0],
                "玩家分组",
                group_options,
                "vip_operations_filter_group",
            )
            selected_server = compact_multiselect_filter(
                st,
                filter_cols[1],
                "区服",
                server_options,
                "vip_operations_filter_zone",
            )
            selected_source = compact_multiselect_filter(
                st,
                filter_cols[2],
                "用户来源",
                source_options,
                "vip_operations_filter_source",
            )
            selected_priority = compact_multiselect_filter(
                st,
                filter_cols[3],
                "触达优先级",
                priority_options,
                "vip_operations_filter_priority",
            )
            st.caption("每项均支持多选；清空任一项时，该项会按全部选项处理。")

        filtered_df = scored_df[
            scored_df["玩家分组"].astype(str).isin(selected_group if selected_group else group_options)
            & scored_df["区服"].astype(str).isin(selected_server if selected_server else server_options)
            & scored_df["用户来源"].astype(str).isin(selected_source if selected_source else source_options)
            & scored_df["触达优先级"].astype(str).isin(selected_priority if selected_priority else priority_options)
        ]
        group_count = len(selected_group) if selected_group else len(group_options)
        server_count = len(selected_server) if selected_server else len(server_options)
        source_count = len(selected_source) if selected_source else len(source_options)
        priority_count = len(selected_priority) if selected_priority else len(priority_options)
        st.markdown(
            f"""
            <div class="filter-state-summary">
                <span class="filter-state-label">已应用条件</span>
                <span>玩家分组 {group_count}/{len(group_options)}</span>
                <span>区服 {server_count}/{len(server_options)}</span>
                <span>用户来源 {source_count}/{len(source_options)}</span>
                <span>触达优先级 {priority_count}/{len(priority_options)}</span>
                <strong>当前 {len(filtered_df):,} 名玩家</strong>
            </div>
            """,
            unsafe_allow_html=True,
        )
    return filtered_df


def _contact_ranking_frame(dataframe: pd.DataFrame, limit: int = 20) -> pd.DataFrame:
    columns = [
        "排名",
        "排行标签",
        "角色名",
        "角色ID",
        "区服",
        "玩家分组",
        "触达优先级",
        "价值分",
        "风险分",
        "综合风险系数",
        "累计充值",
        "近一周充值",
        "前7日充值",
        "最后登录时间",
        "原因",
    ]
    if dataframe.empty or "触达优先级" not in dataframe.columns:
        return pd.DataFrame(columns=columns)

    output = dataframe[dataframe["触达优先级"].isin(CONTACT_PRIORITIES)].copy()
    if output.empty:
        return pd.DataFrame(columns=columns)
    for column in columns:
        if column not in output.columns:
            output[column] = (
                0
                if column in {"价值分", "风险分", "累计充值", "近一周充值", "前7日充值"}
                else ""
            )
    for column in ("价值分", "风险分", "累计充值", "近一周充值", "前7日充值"):
        output[column] = pd.to_numeric(output[column], errors="coerce").fillna(0)
    output["综合风险系数"] = output["价值分"] + output["风险分"]
    output["角色名"] = output["角色名"].fillna("").astype(str).str.strip().replace("", "未命名玩家")
    output["区服"] = output["区服"].fillna("").astype(str).str.strip().replace("", "未分类")
    output = output.sort_values(
        ["综合风险系数", "风险分", "价值分", "累计充值"],
        ascending=[False, False, False, False],
        kind="stable",
    ).head(max(int(limit), 0)).reset_index(drop=True)
    output["排名"] = range(1, len(output) + 1)
    output["排行标签"] = [
        f"{rank:02d}  {name} · S{zone}" if str(zone).isdigit() else f"{rank:02d}  {name} · {zone}"
        for rank, name, zone in zip(output["排名"], output["角色名"], output["区服"], strict=False)
    ]
    return output[columns]


def _server_label(value: object) -> str:
    label = str(value).strip()
    numeric = pd.to_numeric(label, errors="coerce")
    if pd.notna(numeric) and float(numeric).is_integer():
        return f"S{int(numeric)}"
    return label or "未分类"


def _render_contact_ranking(st, dataframe: pd.DataFrame) -> None:
    ranking = _contact_ranking_frame(dataframe)
    total_contacts = (
        int(dataframe["触达优先级"].isin(CONTACT_PRIORITIES).sum())
        if "触达优先级" in dataframe.columns
        else 0
    )
    with st.container(key="vip_insight_ranking"):
        if ranking.empty:
            st.markdown(
                """
                <div class="vip-ranking-panel">
                    <div class="vip-ranking-panel-header">
                        <div>
                            <div class="vip-ranking-panel-title">综合风险系数 Top 20</div>
                            <div class="vip-ranking-panel-copy">综合风险系数 = 价值分 + 风险分</div>
                        </div>
                    </div>
                    <div class="vip-ranking-empty">当前筛选条件下没有需要立即或优先触达的玩家。</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            return

        maximum_score = max(float(ranking["综合风险系数"].max()), 1.0)
        rows: list[str] = []
        for row_index, row in ranking.iterrows():
            priority_label = str(row["触达优先级"])
            tone = "immediate" if priority_label == "立即触达" else "priority"
            top_class = " top-three" if int(row["排名"]) <= 3 else ""
            bar_width = max(3.0, min(float(row["综合风险系数"]) / maximum_score * 100, 100.0))
            reason = str(row.get("原因") or "暂无触达原因")
            title = escape(
                f"角色ID：{row['角色ID']} · 累计充值：{float(row['累计充值']):,.2f} · "
                f"近7日充值：{float(row['近一周充值']):,.2f} · "
                f"前7日充值：{float(row['前7日充值']):,.2f} · {reason}"
            )
            last_login = escape(str(row.get("最后登录时间") or "-"))
            role_id = escape(str(row.get("角色ID") or "-"))
            rows.append(
                f'<details class="vip-ranking-entry" title="{title}">'
                f'<summary class="vip-ranking-row {tone}{top_class}" '
                f'style="--row-index:{row_index};--bar-width:{bar_width:.1f}%">'
                f'<span class="vip-rank-number">{int(row["排名"]):02d}</span>'
                f'<div class="vip-rank-player"><strong>{escape(str(row["角色名"]))}'
                f'<em class="vip-player-hint">点击查看</em></strong>'
                f'<span>{escape(_server_label(row["区服"]))} · {escape(str(row["玩家分组"]))}</span></div>'
                f'<span class="vip-priority-chip {tone}">{escape(priority_label)}</span>'
                f'<span class="vip-score-pair"><span>价值 <b>{float(row["价值分"]):.0f}</b></span>'
                f'<span>风险 <b>{float(row["风险分"]):.0f}</b></span></span>'
                f'<strong class="vip-composite-score">{float(row["综合风险系数"]):.0f}</strong>'
                f'<span class="vip-ranking-progress"><span></span></span></summary>'
                f'<div class="vip-player-detail">'
                f'<div class="vip-player-detail-item"><span>角色 ID · 可框选复制</span><code>{role_id}</code></div>'
                f'<div class="vip-player-detail-item"><span>累计充值</span><strong>{float(row["累计充值"]):,.2f}</strong></div>'
                f'<div class="vip-player-detail-item"><span>近 7 日充值</span><strong>{float(row["近一周充值"]):,.2f}</strong></div>'
                f'<div class="vip-player-detail-item"><span>前 7 日充值</span><strong>{float(row["前7日充值"]):,.2f}</strong></div>'
                f'<div class="vip-player-detail-item"><span>最后登录</span><strong>{last_login}</strong></div>'
                f'</div></details>'
            )

        st.markdown(
            '<div class="vip-ranking-panel">'
            '<div class="vip-ranking-panel-header"><div>'
            '<div class="vip-ranking-panel-title">综合风险系数 Top 20</div>'
            '<div class="vip-ranking-panel-copy">价值体现影响程度，风险体现流失可能；系数越高越应优先触达。</div>'
            f'</div><span class="vip-ranking-panel-count">显示 {len(ranking)} / {total_contacts}</span></div>'
            '<div class="vip-ranking-table-head"><span>#</span><span>玩家 / 区服</span>'
            '<span>优先级</span><span>分数组成</span><span>系数</span></div>'
            f'<div class="vip-ranking-list">{"".join(rows)}</div></div>',
            unsafe_allow_html=True,
        )


def _server_contact_frame(dataframe: pd.DataFrame, limit: int = 12) -> pd.DataFrame:
    if dataframe.empty:
        return pd.DataFrame(columns=["区服", "待触达人数", "区服标签"])
    output = server_contact_counts(dataframe).head(limit).copy()
    if output.empty:
        return pd.DataFrame(columns=["区服", "待触达人数", "区服标签"])

    output["区服标签"] = output["区服"].map(_server_label)
    return output[["区服", "待触达人数", "区服标签"]]


def _render_server_contact_chart(st, dataframe: pd.DataFrame) -> None:
    servers = _server_contact_frame(dataframe)
    with st.container(key="vip_insight_servers"):
        if servers.empty:
            st.markdown(
                """
                <div class="vip-ranking-panel">
                    <div class="vip-ranking-panel-header">
                        <div>
                            <div class="vip-ranking-panel-title">区服待触达 Top 12</div>
                            <div class="vip-ranking-panel-copy">按合服后区服汇总待触达玩家</div>
                        </div>
                    </div>
                    <div class="vip-ranking-empty">当前筛选条件下暂无待触达区服。</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            return

        maximum_count = max(int(servers["待触达人数"].max()), 1)
        rows: list[str] = []
        for row_index, row in servers.reset_index(drop=True).iterrows():
            rank = row_index + 1
            top_class = " top-three" if rank <= 3 else ""
            count = int(row["待触达人数"])
            bar_width = max(3.0, min(count / maximum_count * 100, 100.0))
            rows.append(
                f'<div class="vip-server-row{top_class}" '
                f'style="--row-index:{row_index};--bar-width:{bar_width:.1f}%" '
                f'title="{escape(str(row["区服标签"]))} · {count:,} 名待触达玩家">'
                f'<span class="vip-server-rank">{rank:02d}</span>'
                f'<strong class="vip-server-name">{escape(str(row["区服标签"]))}</strong>'
                '<span class="vip-server-track"><span></span></span>'
                f'<strong class="vip-server-count">{count:,}</strong></div>'
            )
        st.markdown(
            '<div class="vip-ranking-panel">'
            '<div class="vip-ranking-panel-header"><div>'
            '<div class="vip-ranking-panel-title">区服待触达 Top 12</div>'
            '<div class="vip-ranking-panel-copy">仅统计立即与优先触达玩家，并按合服后区服汇总。</div>'
            f'</div><span class="vip-ranking-panel-count">{len(servers)} 个区服</span></div>'
            '<div class="vip-server-table-head"><span>#</span><span>区服</span>'
            '<span>相对规模</span><span>人数</span></div>'
            f'<div class="vip-server-list">{"".join(rows)}</div></div>',
            unsafe_allow_html=True,
        )


def _render_player_insights(st, dataframe: pd.DataFrame, total_count: int) -> None:
    contact_total = (
        int(dataframe["触达优先级"].isin(CONTACT_PRIORITIES).sum())
        if "触达优先级" in dataframe.columns
        else 0
    )
    immediate_count = (
        int(dataframe["触达优先级"].eq("立即触达").sum())
        if "触达优先级" in dataframe.columns
        else 0
    )
    priority_count = max(contact_total - immediate_count, 0)
    server_count = len(server_contact_counts(dataframe)) if contact_total else 0
    drawer_label = f"优先触达洞察 · {contact_total:,} 名待触达玩家"
    with st.container(key="vip_contact_insight_drawer"):
        with st.expander(drawer_label, expanded=True):
            st.markdown(
                '<div class="vip-insight-summary">'
                f'<div class="vip-insight-summary-item"><span>筛选玩家</span><strong>{len(dataframe):,} / {total_count:,}</strong></div>'
                f'<div class="vip-insight-summary-item attention"><span>立即触达</span><strong>{immediate_count:,}</strong></div>'
                f'<div class="vip-insight-summary-item"><span>优先触达</span><strong>{priority_count:,}</strong></div>'
                f'<div class="vip-insight-summary-item"><span>覆盖区服</span><strong>{server_count:,} 个</strong></div>'
                '</div>',
                unsafe_allow_html=True,
            )
            insight_columns = st.columns([1.45, 1], gap="large")
            with insight_columns[0]:
                _render_contact_ranking(st, dataframe)
            with insight_columns[1]:
                _render_server_contact_chart(st, dataframe)


def _render_player_export(st, dataframe: pd.DataFrame, total_count: int) -> None:
    section(st, "数据导出", "保留完整字段，导出内容与当前筛选结果一致。", "download")
    with st.container(key="vip_player_export"):
        export_columns = st.columns([1, 0.34])
        export_columns[0].markdown(
            f"**当前筛选结果**  将导出 {len(dataframe):,} / {total_count:,} 名玩家"
        )
        export_columns[1].download_button(
            "导出当前结果 Excel",
            data=dataframe_to_excel_bytes(dataframe),
            file_name=f"VIP玩家评分明细_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            width="stretch",
        )


def render(st, db_path) -> None:
    _vip_overview_css(st)
    st.session_state.setdefault("vip_upload_widget_version", 0)
    _render_data_source(st, db_path)
    source = _current_source(st, db_path)
    if source is None:
        st.warning("请先从 AE 项目 24 同步数据，或上传一个 .xlsx 回退文件。")
        return

    try:
        workbook = load_current_workbook(st, db_path)
    except Exception as exc:
        st.error(f"处理失败：{exc}")
        return

    if workbook.abnormal_count:
        st.warning(f"发现 {workbook.abnormal_count} 条数据无法识别服务器类型或用户来源，已标记为“未分类”。")
    if workbook.missing_page_columns:
        st.warning("页面已自动补齐缺失字段：" + "、".join(workbook.missing_page_columns))

    metrics = vip_summary_metrics(workbook)
    section(st, "数据概览", "核心待触达人数仅统计非退游玩家。", "bar")
    st.caption(f"当前合服统计口径：{server_merge_summary()}。原区服保留在玩家明细中。")
    _render_vip_metric_band(
        st,
        [
            ("总玩家", metrics["总玩家"], "当前数据源中的 VIP 玩家", ""),
            ("有效玩家", metrics["有效玩家"], f"排除退游或达到 {RETIREMENT_INACTIVITY_DAYS} 天未登录玩家", ""),
            ("待触达", metrics["待触达"], "立即触达 + 优先触达", "attention"),
            ("退游玩家", metrics["退游玩家"], "不纳入触达统计", ""),
            ("未分类", metrics["未分类"], "需要检查来源或区服", ""),
        ],
        "primary",
    )
    _render_vip_metric_band(
        st,
        [
            ("老服自然量待触达", contact_count_for_group(workbook.active_df, "老服自然量"), "老服自然量", ""),
            ("老服 CPS 待触达", contact_count_for_group(workbook.active_df, "老服CPS"), "老服 CPS", ""),
            ("新服自然量待触达", contact_count_for_group(workbook.active_df, "新服自然量"), "新服自然量", ""),
            ("新服 CPS 待触达", contact_count_for_group(workbook.active_df, "新服CPS"), "新服 CPS", ""),
        ],
        "secondary",
    )

    section(st, "玩家洞察", "按综合风险系数与合服后区服，快速定位优先触达对象。", "filter")
    st.caption(
        "风险口径：7 天未登录进入观察，14 天进入高风险，30 天计为退游；"
        "充值按近 7 日与前 7 日两个窗口观察，连续 14 日未充值会进一步提高风险。"
    )
    filtered_df = _filter_dataframe(st, workbook.scored_df)
    display_df = filtered_df.drop(columns=list(HIDDEN_DETAIL_COLUMNS), errors="ignore")
    _render_player_insights(st, display_df, len(workbook.scored_df))
    _render_player_export(st, display_df, len(workbook.scored_df))
