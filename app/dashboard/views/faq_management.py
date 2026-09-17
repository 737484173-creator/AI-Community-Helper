from __future__ import annotations

from datetime import datetime
from html import escape

from app.dashboard.views.vip_common import section
from app.database.repositories.faq_repository import FAQRepository
from app.utils.excel_importer import FAQImportResult, import_faq_from_excel
from config.settings import BASE_DIR


FAQ_SOURCE_FILE = BASE_DIR / "data" / "faq" / "current_faq.xlsx"


def _format_file_size(size_bytes: int) -> str:
    if size_bytes >= 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.2f} MB"
    if size_bytes >= 1024:
        return f"{size_bytes / 1024:.1f} KB"
    return f"{size_bytes} B"


def _faq_record_count(repository: FAQRepository) -> int:
    """Support an already-running dashboard that still holds the older repository class."""
    count_all = getattr(repository, "count_all", None)
    if callable(count_all):
        return int(count_all())
    return len(repository.list_all(limit=1_000_000))


def _import_uploaded_file(uploaded_file: object, db_path) -> FAQImportResult:
    FAQ_SOURCE_FILE.parent.mkdir(parents=True, exist_ok=True)
    pending_file = FAQ_SOURCE_FILE.with_name(".current_faq.pending.xlsx")
    pending_file.write_bytes(uploaded_file.getvalue())
    try:
        result = import_faq_from_excel(pending_file, db_path)
        pending_file.replace(FAQ_SOURCE_FILE)
    except Exception:
        pending_file.unlink(missing_ok=True)
        raise
    return result


def _render_file_status(st, repository: FAQRepository) -> None:
    if FAQ_SOURCE_FILE.exists():
        file_stat = FAQ_SOURCE_FILE.stat()
        file_name = FAQ_SOURCE_FILE.name
        file_size = _format_file_size(file_stat.st_size)
        modified_time = datetime.fromtimestamp(file_stat.st_mtime).strftime("%Y-%m-%d %H:%M")
        status = "当前文件"
    else:
        file_name = "尚未上传 FAQ 文档"
        file_size = "-"
        modified_time = "-"
        status = "等待上传"

    st.markdown(
        f"""
        <div class="event-effect-card">
            <div class="event-effect-title">文件状态</div>
            <div class="status-row">
                <span class="status-pill info">状态：{status}</span>
                <span class="status-pill neutral">知识条目：{_faq_record_count(repository):,}</span>
                <span class="status-pill neutral">大小：{file_size}</span>
                <span class="status-pill neutral">时间：{modified_time}</span>
            </div>
            <div class="report-preview-meta">{escape(file_name)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    with st.popover("查看当前 FAQ 文件位置", use_container_width=True):
        if FAQ_SOURCE_FILE.exists():
            st.caption("当前 FAQ 文档保存在：")
        else:
            st.caption("首次成功导入后，FAQ 文档将保存在：")
        st.code(str(FAQ_SOURCE_FILE), language=None)


def render(st, db_path) -> None:
    repository = FAQRepository(db_path)

    section(
        st,
        "FAQ 数据源",
        "上传最新 Excel 文档并更新 AI 助手知识库；页面仅保留文件状态，不再展开原始明细。",
        "upload",
    )

    upload_cols = st.columns(2)
    with upload_cols[0]:
        uploaded_file = st.file_uploader(
            "上传 FAQ Excel 文件",
            type=["xlsx"],
            key="faq_excel_upload",
            help="支持 .xlsx 文件；成功导入后会保存一份当前文档供后续查看。",
        )
        submitted = st.button(
            "导入并更新 FAQ",
            type="primary",
            use_container_width=True,
            disabled=uploaded_file is None,
        )
        if submitted and uploaded_file is not None:
            try:
                with st.spinner("正在导入 FAQ…"):
                    result = _import_uploaded_file(uploaded_file, db_path)
                st.success(
                    f"已导入 {result.imported_count} 条 FAQ，"
                    f"跳过 {result.skipped_count} 条。"
                )
            except Exception as exc:
                st.error(f"导入失败：{exc}")

    with upload_cols[1]:
        _render_file_status(st, repository)
