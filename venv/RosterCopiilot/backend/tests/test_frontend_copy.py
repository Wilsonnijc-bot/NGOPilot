"""Guard the demo UI copy: a Traditional Chinese wizard, not an importer tool.

The main user path must read as "upload HC + escort, pick week, generate,
download"; importer/debug vocabulary stays out of the visible copy (the
collapsed developer-tools block is the only allowed exception).
"""
from __future__ import annotations

import re
from pathlib import Path

FRONTEND_INDEX = Path(__file__).resolve().parents[2] / "frontend" / "index.html"

REQUIRED_WIZARD_COPY = [
    "上載 HC 時間表",
    "上載護送總表",
    "選擇目標週與變更",
    "生成並下載",
    "生成排班表",
    "下載審核草稿",
    "固定基礎",
]

FORBIDDEN_VISIBLE_COPY = [
    "匯入",  # importer vocabulary
    "導入",
    "除錯",  # debug vocabulary
    "importer",
    "debug",
]


def _html() -> str:
    return FRONTEND_INDEX.read_text(encoding="utf-8")


def _visible_copy(html: str) -> str:
    """Markup without script/style bodies — approximates user-visible copy."""
    text = re.sub(r"<script\b.*?</script>", "", html, flags=re.S | re.I)
    return re.sub(r"<style\b.*?</style>", "", text, flags=re.S | re.I)


def test_frontend_is_traditional_chinese_wizard():
    html = _html()
    assert 'lang="zh-Hant-HK"' in html
    for copy in REQUIRED_WIZARD_COPY:
        assert copy in html, f"wizard copy missing: {copy}"


def test_frontend_visible_copy_avoids_importer_and_debug_language():
    visible = _visible_copy(_html()).lower()
    for term in FORBIDDEN_VISIBLE_COPY:
        # element ids/attributes may mention imports for the dev-only check
        # button; visible text must not.
        occurrences = [
            match for match in re.finditer(re.escape(term.lower()), visible)
        ]
        for match in occurrences:
            context = visible[max(0, match.start() - 40): match.end() + 40]
            assert re.search(r'(id|class|data-\w+)="[^"]*$',
                             visible[:match.start()]), (
                f"forbidden term {term!r} appears in visible copy: …{context}…"
            )


def test_frontend_dev_tools_are_collapsed_support_section():
    html = _html()
    assert '<details class="dev-tools">' in html
    assert "open" not in html.split('<details class="dev-tools"', 1)[1].split(">", 1)[0]
    assert "不屬於用戶主流程" in html


def test_frontend_renders_impact_and_audit_sections():
    html = _html()
    for anchor in ("臨時變更影響", "審核項目", "impactList", "auditList"):
        assert anchor in html, f"result section wiring missing: {anchor}"
    for removed in ("未分配任務", "unassignedList", "renderUnassigned"):
        assert removed not in html, f"standalone unassigned section remains: {removed}"
    assert "audit-kind-unassigned_task" in html


def test_frontend_can_queue_multiple_temporary_changes():
    html = _html()
    for anchor in (
        "addChangeBtn",
        "pendingChangeList",
        "pendingChanges: []",
        "state.pendingChanges.push(draft)",
        "JSON.stringify(changes)",
    ):
        assert anchor in html, f"multiple-change UI wiring missing: {anchor}"


def test_frontend_audit_categories_and_quick_review_tools_are_wired():
    html = _html()
    for anchor in (
        "auditFilters",
        "data-audit-filter",
        "data-audit-kind",
        "audit-kind-exclusive_cancellation",
        "audit-kind-unassigned_task",
        "quickReviewer",
        "quickReason",
        "applyQuickReviewer",
        "applyQuickReason",
        "visiblePendingAuditCards",
        "一鍵強制忽略目前分類",
        "bulkHardBypassVisible",
    ):
        assert anchor in html, f"audit UX wiring missing: {anchor}"


def test_frontend_audit_cards_explain_task_people_time_and_reason():
    html = _html()
    for copy in (
        "任務",
        "涉及同工",
        "涉及長者",
        "日期／時段",
        "問題摘要",
        "無法完成原因",
    ):
        assert copy in html, f"audit context label missing: {copy}"
    for helper in (
        "auditContext(item)",
        "auditRelatedEntries(item)",
        "auditTimeLabel",
        "auditWorkerHints",
    ):
        assert helper in html, f"audit context wiring missing: {helper}"


def test_frontend_omits_redundant_schedule_preview():
    html = _html()
    for removed in (
        "總排班預覽",
        "scheduleRows",
        "previewNote",
        "function renderSchedule",
    ):
        assert removed not in html, f"redundant preview remains: {removed}"


def test_frontend_restores_workspace_and_manages_immutable_archives():
    html = _html()
    for anchor in (
        "工作狀態與存檔",
        "saveWorkspaceBtn",
        "archiveRunBtn",
        "resumeWorkspaceBtn",
        "scheduleWorkspaceAutosave",
        'apiJson("/api/demo/workspace"',
        'apiJson("/api/demo/archives"',
        "固態存檔是不可變的只讀快照",
        "從此存檔建立可編輯副本",
        "/editable-copy",
    ):
        assert anchor in html, f"workspace/archive wiring missing: {anchor}"


def test_c08_frontend_keeps_one_flow_and_exposes_review_actions():
    html = _html()
    for copy in (
        "上載 HC 時間表",
        "上載護送總表",
        "生成排班表",
        "審核項目",
        "批准",
        "修改",
        "強制略過（Hard-bypass）",
        "審核人（必填）",
        "備註（修改／強制略過必填）",
        "下載審核草稿",
    ):
        assert copy in html
    assert "/review-decisions" in html
    assert "/revalidate" in html
    assert "發佈正式版" in _visible_copy(html)
    assert "下載正式版" in _visible_copy(html)
    render_audit = html.split("function renderAudit(items)", 1)[1].split(
        "function reviewTargetEntry", 1
    )[0]
    assert "const shown = items;" in render_audit
    assert ".slice(0, 12)" not in render_audit


def test_c09_frontend_uses_server_reconciliation_totals_and_state():
    html = _html()
    render_run = html.split("function renderRun(run)", 1)[1].split(
        "function renderImpacts", 1
    )[0]
    assert "const reconciliation = run.reconciliation" in render_run
    for field in (
        "reconciliation.publication_state",
        "reconciliation.placement_count",
        "reconciliation.unassigned",
        "reconciliation.pending_audit_counts",
    ):
        assert field in render_run
    assert "gen.entries" not in render_run
    assert "gen.unassigned" not in render_run
    assert "audit_items.length" not in render_run
    assert "unassigned_items.length" not in render_run


def test_frontend_review_controls_guard_concurrent_submissions():
    html = _html()
    for anchor in (
        "state.isBusy",
        "正在處理上一個審核操作，請稍候。",
        "#auditList [data-review-action], #auditList [data-review-field], #auditList [data-edit-field]",
        "beginButtonProcessing",
        "處理中…",
        "data-locked",
    ):
        assert anchor in html, f"busy-guard wiring missing: {anchor}"
    handle_audit = html.split("async function handleAuditAction(event)", 1)[1].split(
        "async function revalidateRoster", 1
    )[0]
    assert "state.isBusy" in handle_audit
    assert "reviewIdempotencyKey(" in handle_audit
    # every review submission must go through the reusable-key helper
    assert "idempotency_key: newIdempotencyKey()" not in html


def test_frontend_review_retries_reuse_key_and_stale_conflicts_reload():
    html = _html()
    for anchor in (
        "function reviewIdempotencyKey",
        "state.pendingReview",
        "function isStaleReviewError",
        "STALE_SCHEDULE_VERSION",
        "STALE_CONTENT_HASH",
        "function reloadCurrentRun",
        "error.status = res.status",
        "已自動重新載入最新排班版本",
    ):
        assert anchor in html, f"stale-retry wiring missing: {anchor}"
