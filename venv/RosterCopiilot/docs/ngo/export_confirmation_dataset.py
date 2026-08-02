#!/usr/bin/env python3
"""Export the prefilled NGO confirmation dataset as JSON.

Strict data-boundary policy
---------------------------
Everything in this export must be traceable to a cell in the source
workbooks or to an explicitly-labelled project-team interpretation.
The bootstrap master data (``bootstrap_master_data_from_template``) is
deliberately NOT used here because it silently fills gaps:

* seed skill facts (414 rows, source="seed") are demo assumptions;
* missing work hours are defaulted to 08:30-17:30;
* untagged workers are defaulted to a home team;
* elder gender requirement defaults to "ANY".

None of those defaults may be presented to the NGO as observed facts, so
this script reads the raw parser output instead and leaves gaps blank.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from openpyxl import load_workbook

from backend.app.importer.division import parse_division_workbook
from backend.app.importer.skills import parse_skills_sheet

SOURCE_DIVISION = ROOT / "docs" / "照顧員工作分工表2026(HKU).xlsx"

WEEKDAYS = {1: "星期一", 2: "星期二", 3: "星期三", 4: "星期四", 5: "星期五", 6: "星期六"}
PERIODS = {"AM": "上午", "PM": "下午"}
KIND_LABELS = {
    "meal": "送飯",
    "escort_slot": "護送預留（ESC）",
    "kitchen": "廚房工作",
    "logistics": "其他工作／物流",
    "off": "OFF（原表休息標記）",
}


def _cell(a) -> str:
    return f"{a.cell.sheet_name}!R{a.cell.row}C{a.cell.column}" if a.cell else ""


def _detail_time(a) -> str:
    det = a.detail
    if not det:
        return ""
    start = det.start_time or ""
    end = det.end_time or ""
    if start and end:
        return f"{start}-{end}"
    return start or end or ""


def build_dataset() -> dict:
    division = parse_division_workbook(SOURCE_DIVISION)

    # ------------------------------------------------------------------ workers
    worker_rows = []
    for w in division.workers:
        worker_rows.append(
            {
                "display_name": w.display_name,
                "raw_header": w.raw_header or "",
                "tags": "、".join(w.tags or []),
                "work_hours_raw": w.work_hours_raw or "",
                "saturday_team": w.saturday_team or "",
                "saturday_raw": (w.saturday_raw or "").strip(),
                "status_inferred": (
                    "在職（表內欄位如常使用）"
                    if w.status_inferred == "active"
                    else "狀態待確認（欄位以灰色顯示）"
                ),
                "column_letter": w.column_letter,
            }
        )

    workers_missing_hours = [w.display_name for w in division.workers if not w.work_hours_raw]
    workers_missing_saturday = [
        w.display_name for w in division.workers if not w.saturday_team
    ]
    workers_grey = [
        w.display_name for w in division.workers if w.status_inferred != "active"
    ]
    workers_untagged = [w.display_name for w in division.workers if not w.tags]

    # -------------------------------------------------------------- assignments
    by_kind: dict[str, list] = defaultdict(list)
    for a in division.assignments:
        by_kind[a.kind].append(a)

    field_rows = []
    for a in sorted(by_kind["field_service"], key=lambda x: (x.weekday, x.period != "AM", x.cell.column if x.cell else 0)):
        det = a.detail
        field_rows.append(
            {
                "weekday": WEEKDAYS.get(a.weekday, str(a.weekday)),
                "period": PERIODS.get(a.period, a.period),
                "raw_text": a.raw_text or "",
                "elder_alias": a.elder_alias or "",
                "unit": a.unit or "",
                "service_code": a.service_code_raw or "",
                "time": _detail_time(a),
                "district": (det.district if det else None) or "",
                "week_pattern": a.week_pattern_raw or "每週（表內無另行標註）",
                "worker": a.worker_alias or "",
                "notes": "；".join(
                    x
                    for x in [
                        a.inline_note,
                        det.trailing_label if det else None,
                        det.role_note if det else None,
                    ]
                    if x
                ),
                "source_cell": _cell(a),
            }
        )

    centre_workers: dict[tuple, set] = defaultdict(set)
    centre_roles: dict[tuple, set] = defaultdict(set)
    for a in by_kind["center_duty"]:
        if not a.duty_center:
            continue
        key = (a.duty_center, a.weekday, a.period)
        centre_workers[key].add(a.worker_alias)
        role = a.duty_role or (a.detail.role_note if a.detail else None)
        if role:
            centre_roles[key].add(str(role))

    centre_rows = []
    for centre in ("AMC", "MRC", "GC"):
        for weekday in range(1, 7):
            for period in ("AM", "PM"):
                key = (centre, weekday, period)
                names = sorted(centre_workers.get(key, set()))
                centre_rows.append(
                    {
                        "centre": centre,
                        "weekday": WEEKDAYS[weekday],
                        "period": PERIODS[period],
                        "observed_count": len(names),
                        "observed_workers": "、".join(names),
                        "observed_roles": "、".join(sorted(centre_roles.get(key, set()))),
                    }
                )

    other_rows = []
    for kind in ("meal", "escort_slot", "kitchen", "logistics", "off"):
        for a in sorted(by_kind[kind], key=lambda x: (x.weekday, x.period != "AM", x.worker_alias or "")):
            other_rows.append(
                {
                    "kind": KIND_LABELS[kind],
                    "weekday": WEEKDAYS.get(a.weekday, str(a.weekday)),
                    "period": PERIODS.get(a.period, a.period),
                    "worker": a.worker_alias or "",
                    "raw_text": a.raw_text or "",
                    "time": _detail_time(a),
                    "place": a.route_or_place or "",
                    "notes": a.inline_note or "",
                    "source_cell": _cell(a),
                }
            )

    # ------------------------------------------------------------ skills matrix
    wb = load_workbook(SOURCE_DIVISION, data_only=True)
    skills_result = parse_skills_sheet(wb["新同工跟服務紀錄表"])
    skill_workers = []
    skill_items: list[tuple[str, str]] = []
    seen_items = set()
    ticks: dict[str, set[tuple[str, str]]] = {}
    for rec in skills_result.records:
        payload = rec.record
        alias = payload["worker_alias"]
        skill_workers.append(
            {"alias": alias, "join_date_raw": payload.get("join_date_raw") or ""}
        )
        ticks[alias] = set()
        for tick in payload["ticks"]:
            key = (tick["category"], tick["item"])
            if key not in seen_items:
                seen_items.add(key)
                skill_items.append(key)
            ticks[alias].add(key)
    skill_matrix = [
        {
            "category": category,
            "item": item,
            "ticks": {
                w["alias"]: ("✓" if (category, item) in ticks[w["alias"]] else "")
                for w in skill_workers
            },
        }
        for category, item in skill_items
    ]

    # ---------------------------------------------------------------- transfers
    transfer_rows = []
    ws = wb["個案轉移紀錄_2025"]
    headers = [c.value for c in ws[1]]
    for row in ws.iter_rows(min_row=2, values_only=True):
        if not any(v is not None and str(v).strip() for v in row):
            continue
        transfer_rows.append(
            {
                str(h): ("" if v is None else str(v))
                for h, v in zip(headers, row)
                if h is not None
            }
        )

    return {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "source_file": SOURCE_DIVISION.name,
        "summary": {
            "workers": len(worker_rows),
            "assignment_units": len(division.assignments),
            "field_services": len(field_rows),
            "centre_slots": len(centre_rows),
            "other_units": len(other_rows),
            "skill_matrix_workers": len(skill_workers),
            "transfer_records": len(transfer_rows),
            "workers_missing_hours": workers_missing_hours,
            "workers_missing_saturday": workers_missing_saturday,
            "workers_grey": workers_grey,
            "workers_untagged_count": len(workers_untagged),
        },
        "excluded_by_policy": [
            "seed 技能假設（414 項，source=seed）—— Demo 運作用假設，非觀察事實",
            "缺失工時的 08:30-17:30 預設值 —— 9 位同工原表沒有工時記錄",
            "未標註同工的預設隊伍 —— 25 位同工原表沒有隊伍標籤",
            "長者性別要求預設值 ANY —— 原表沒有性別記錄",
            "路線資格 —— 除歷史技能表正向勾選外，原表沒有可靠記錄",
        ],
        "workers": worker_rows,
        "field_services": field_rows,
        "centre_slots": centre_rows,
        "other_units": other_rows,
        "skill_workers": skill_workers,
        "skill_matrix": skill_matrix,
        "transfers": transfer_rows,
    }


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("Usage: export_confirmation_dataset.py OUTPUT_JSON")
    output = Path(sys.argv[1])
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(build_dataset(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(output)


if __name__ == "__main__":
    main()
