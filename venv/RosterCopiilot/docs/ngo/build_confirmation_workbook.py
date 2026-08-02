#!/usr/bin/env python3
"""Build the NGO-facing prefilled confirmation workbook (xlsx).

Input : JSON produced by export_confirmation_dataset.py
Output: 02_排班資料確認冊（預填）.xlsx

Design rules
------------
* Prefilled (project-team) columns use a light-grey fill; cells the NGO
  is asked to fill use a light-yellow fill.
* Every prefilled sheet has a "整頁快速確認" cell so the NGO can confirm a
  whole sheet with one entry and only write exceptions row by row.
* Gaps are left blank and never filled with guesses or defaults.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

FONT_NAME = "宋体"

C_TITLE = Font(name=FONT_NAME, size=15, bold=True, color="1F3B57")
C_SUB = Font(name=FONT_NAME, size=10, color="444444")
C_HEAD = Font(name=FONT_NAME, size=10, bold=True, color="FFFFFF")
C_BODY = Font(name=FONT_NAME, size=10)
C_BODY_B = Font(name=FONT_NAME, size=10, bold=True)
C_NOTE = Font(name=FONT_NAME, size=9, color="555555")

F_HEAD = PatternFill("solid", fgColor="2E5F73")          # header row
F_PRE = PatternFill("solid", fgColor="F2F2EE")           # prefilled cells
F_REPLY = PatternFill("solid", fgColor="FFF4CC")         # cells to fill in
F_BANNER = PatternFill("solid", fgColor="E8F0EC")        # instruction banner
F_QUICK = PatternFill("solid", fgColor="FFE9A8")         # quick-confirm cell

THIN = Side(style="thin", color="C9C9C9")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)

WRAP = Alignment(wrap_text=True, vertical="top")
WRAP_C = Alignment(wrap_text=True, vertical="center", horizontal="center")


def _set(ws, row, col, value, font=C_BODY, fill=None, align=WRAP, border=True):
    cell = ws.cell(row=row, column=col, value=value)
    cell.font = font
    if fill is not None:
        cell.fill = fill
    cell.alignment = align
    if border:
        cell.border = BORDER
    return cell


def _widths(ws, widths):
    for idx, width in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(idx)].width = width


def _banner(ws, row, ncols, text, fill=F_BANNER, font=C_NOTE, height=None):
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=ncols)
    cell = ws.cell(row=row, column=1, value=text)
    cell.font = font
    cell.fill = fill
    cell.alignment = WRAP
    if height:
        ws.row_dimensions[row].height = height
    return row + 1


def _quick_confirm(ws, row, ncols):
    """Whole-sheet quick confirmation row: label + yellow cell."""
    label_cols = max(1, ncols - 2)
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=label_cols)
    cell = ws.cell(
        row=row,
        column=1,
        value="整頁快速確認：如本頁預填內容全部無誤，請於右方黃色格填寫「確認無誤」，毋須逐行填寫；"
        "如只有少量差異，請只在相關行的黃色欄填寫更正。",
    )
    cell.font = C_BODY_B
    cell.fill = F_BANNER
    cell.alignment = WRAP
    ws.merge_cells(start_row=row, start_column=label_cols + 1, end_row=row, end_column=ncols)
    box = ws.cell(row=row, column=label_cols + 1, value="")
    box.fill = F_QUICK
    box.border = BORDER
    box.font = C_BODY_B
    box.alignment = WRAP_C
    ws.row_dimensions[row].height = 30
    return row + 1


def _header_row(ws, row, headers, reply_from):
    for idx, header in enumerate(headers, start=1):
        cell = _set(ws, row, idx, header, font=C_HEAD, fill=F_HEAD, align=WRAP_C)
    ws.row_dimensions[row].height = 26
    ws.freeze_panes = ws.cell(row=row + 1, column=1)
    return row + 1


def _title(ws, title, subtitle, ncols):
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=ncols)
    cell = ws.cell(row=1, column=1, value=title)
    cell.font = C_TITLE
    cell.alignment = Alignment(vertical="center")
    ws.row_dimensions[1].height = 26
    ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=ncols)
    sub = ws.cell(row=2, column=1, value=subtitle)
    sub.font = C_SUB
    sub.alignment = WRAP
    ws.row_dimensions[2].height = 28
    return 3


def _data_rows(ws, row, rows, reply_from, ncols):
    for record in rows:
        for idx in range(1, ncols + 1):
            value = record[idx - 1] if idx <= len(record) else ""
            fill = F_REPLY if idx >= reply_from else F_PRE
            _set(ws, row, idx, value, fill=fill)
        row += 1
    return row


def build(data: dict, out_path: Path) -> None:
    wb = Workbook()

    # ------------------------------------------------------------------ 讀我
    ws = wb.active
    ws.title = "讀我（請先看這頁）"
    _widths(ws, [16, 88, 22])
    row = _title(
        ws,
        "排班資料確認冊（預填版）",
        f"本冊由本項目團隊根據貴機構提供的文件預先整理及填寫（來源：{data['source_file']}；"
        f"整理日期：{data['generated_at'][:10]}）。貴機構毋須重新輸入資料，只需確認及補充。",
        3,
    )
    row += 1
    steps = [
        ("第 1 步", "逐頁查看各工作表的預填內容（灰色底為我們已填好的部分）。", ""),
        ("第 2 步", "如整頁無誤：只需在該頁頂部的黃色「整頁快速確認」格填寫「確認無誤」。", ""),
        ("第 3 步", "如有少量差異：只在有差異的行的黃色欄填寫更正，其餘行毋須處理。", ""),
        ("第 4 步", "「B-需要提供的資料」一頁是文件中沒有記錄的項目，請按最方便的方式提供。", ""),
        ("第 5 步", "完成後把本檔案電郵回覆即可；亦可改以 WhatsApp 文字、相片、截圖或粵語錄音回覆，由我們代為整理。", ""),
    ]
    for label, text, _ in steps:
        _set(ws, row, 1, label, font=C_BODY_B, fill=F_BANNER)
        ws.merge_cells(start_row=row, start_column=2, end_row=row, end_column=3)
        _set(ws, row, 2, text)
        ws.row_dimensions[row].height = 24
        row += 1
    row += 1
    row = _banner(
        ws, row, 3,
        "三個貼心原則：（1）如資料暫時無法確定，請直接填寫「待確認」或「不適用」，毋須猜測，"
        "亦毋須因少量缺口延遲回覆其他部分；（2）如貴機構持有更新版本的文件，可直接提交最新原檔並註明"
        "「以此為準」，毋須逐行比較或自行合併；（3）任何格式我們都接受，整理工作由本項目團隊負責。",
        height=48, font=C_BODY,
    )
    row += 1
    _set(ws, row, 1, "顏色說明", font=C_BODY_B, fill=F_BANNER); row += 1
    _set(ws, row, 1, "", fill=F_PRE)
    ws.merge_cells(start_row=row, start_column=2, end_row=row, end_column=3)
    _set(ws, row, 2, "灰色底＝我們已預填的內容，僅供核對，毋須改動。")
    row += 1
    _set(ws, row, 1, "", fill=F_REPLY)
    ws.merge_cells(start_row=row, start_column=2, end_row=row, end_column=3)
    _set(ws, row, 2, "黃色底＝請貴機構填寫的位置（多數情況下只需填寫極少量）。")
    row += 1
    row = _banner(
        ws, row, 3,
        "填寫示例：假設 A2 頁某一行的服務時間與現況不符，只需在該行黃色「確認／更正」欄填寫"
        "「時間應為 9:00-10:30」；其餘正確的行毋須填寫任何內容，整頁再配合頂部「確認無誤」即可。",
        height=32, font=C_BODY,
    )
    row += 1

    _set(ws, row, 1, "工作表", font=C_HEAD, fill=F_HEAD, align=WRAP_C)
    _set(ws, row, 2, "內容", font=C_HEAD, fill=F_HEAD, align=WRAP_C)
    _set(ws, row, 3, "預填行數", font=C_HEAD, fill=F_HEAD, align=WRAP_C)
    row += 1
    toc = [
        ("A1-同工名單", "46 位同工的代號、標籤、工作時間、星期六組別及推定狀態。", "46"),
        ("A2-恆常服務", "固定上門服務：長者代號、服務、星期、時間、週次及現時負責同工。", str(data['summary']['field_services'])),
        ("A3-中心當值", "AMC／MRC／GC 每半日在表內出現的當值同工及角色；並請補充所需人數。", "36"),
        ("A4-送飯護送廚房及其他", "送飯、護送預留、廚房、其他工作及 OFF 標記的現有安排。", str(data['summary']['other_units'])),
        ("A5-技能記錄", "歷史「新同工跟服務紀錄表」中 6 位同工的正向勾選（✓）。", str(len(data['skill_matrix']))),
        ("A6-個案轉移紀錄", "2025 年個案轉移紀錄，請確認現況。", str(data['summary']['transfer_records'])),
        ("B-需要提供的資料", "文件中沒有可靠記錄、需要貴機構提供的項目（接受任何格式）。", "—"),
    ]
    for name, desc, count in toc:
        _set(ws, row, 1, name, font=C_BODY_B, fill=F_PRE)
        _set(ws, row, 2, desc, fill=F_PRE)
        _set(ws, row, 3, count, fill=F_PRE, align=WRAP_C)
        row += 1

    # ------------------------------------------------------------- A1 workers
    ws = wb.create_sheet("A1-同工名單")
    headers = [
        "同工代號", "原表欄頭", "原表標籤", "原表工作時間", "星期六組別",
        "星期六原文", "推定狀態",
        "確認／更正", "性別（男／女）", "全職／兼職", "所屬隊伍", "備註",
    ]
    _widths(ws, [10, 14, 9, 13, 9, 16, 22, 12, 11, 10, 10, 18])
    ncols = len(headers)
    row = _title(
        ws, "A1　同工名單（預填，請確認）",
        "灰色欄為原表讀取的內容。空白代表原表沒有記錄（並非代表沒有），請在黃色欄補充；"
        "「推定狀態」一欄中，灰色欄位的同工只代表狀態待確認，並非我們認定已離職。",
        ncols,
    )
    row = _quick_confirm(ws, row, ncols)
    row = _header_row(ws, row, headers, reply_from=8)
    rows = [
        [
            w["display_name"], w["raw_header"], w["tags"], w["work_hours_raw"],
            w["saturday_team"], w["saturday_raw"], w["status_inferred"],
            "", "", "", "", "",
        ]
        for w in data["workers"]
    ]
    _data_rows(ws, row, rows, reply_from=8, ncols=ncols)
    ws.auto_filter.ref = f"A{row-1}:{get_column_letter(ncols)}{row-1+len(rows)}"

    # ------------------------------------------------------- A2 field services
    ws = wb.create_sheet("A2-恆常服務")
    headers = [
        "星期", "上／下午", "服務原文", "長者代號", "單位", "服務代號",
        "時間", "地區", "週次", "現時負責同工", "表內備註", "原表位置",
        "確認／更正", "備註",
    ]
    _widths(ws, [8, 8, 20, 10, 7, 9, 13, 10, 14, 11, 12, 14, 12, 16])
    ncols = len(headers)
    row = _title(
        ws, "A2　恆常服務（預填，請確認）",
        "每行對應原分工表一格。請特別留意：現時負責同工暫按「目前安排」理解；"
        "如某些服務屬「只可由此同工負責」的硬性指定，請在該行備註「硬性」。"
        "週次顯示「每週」者為表內無另行標註。",
        ncols,
    )
    row = _quick_confirm(ws, row, ncols)
    row = _header_row(ws, row, headers, reply_from=13)
    rows = [
        [
            s["weekday"], s["period"], s["raw_text"], s["elder_alias"], s["unit"],
            s["service_code"], s["time"], s["district"], s["week_pattern"],
            s["worker"], s["notes"], s["source_cell"], "", "",
        ]
        for s in data["field_services"]
    ]
    _data_rows(ws, row, rows, reply_from=13, ncols=ncols)
    ws.auto_filter.ref = f"A{row-1}:{get_column_letter(ncols)}{row-1+len(rows)}"

    # --------------------------------------------------------- A3 centre slots
    ws = wb.create_sheet("A3-中心當值")
    headers = [
        "中心", "星期", "上／下午", "表內出現人數", "表內當值同工", "表內角色標註",
        "確認／更正", "正常需要人數", "最低安全人數", "備註（特殊崗位等）",
    ]
    _widths(ws, [8, 9, 9, 12, 34, 18, 12, 12, 12, 20])
    ncols = len(headers)
    row = _title(
        ws, "A3　中心當值（預填＋請補充人數）",
        "「表內出現人數」只代表樣本表內實際安排的人數，不一定等於正常需要或最低安全人數，"
        "故此頁同時設有黃色欄請貴機構補充。如整個中心情況相同，亦可只在第一行填寫並註明「以下同」。",
        ncols,
    )
    row = _quick_confirm(ws, row, ncols)
    row = _header_row(ws, row, headers, reply_from=7)
    rows = [
        [
            c["centre"], c["weekday"], c["period"], c["observed_count"],
            c["observed_workers"], c["observed_roles"], "", "", "", "",
        ]
        for c in data["centre_slots"]
    ]
    _data_rows(ws, row, rows, reply_from=7, ncols=ncols)

    # ---------------------------------------------------------- A4 other units
    ws = wb.create_sheet("A4-送飯護送廚房及其他")
    headers = [
        "類別", "星期", "上／下午", "同工", "內容原文", "時間", "地點／路線",
        "表內備註", "原表位置", "確認／更正", "備註",
    ]
    _widths(ws, [17, 8, 8, 9, 18, 12, 12, 14, 14, 12, 16])
    ncols = len(headers)
    row = _title(
        ws, "A4　送飯、護送預留、廚房、其他工作及 OFF（預填，請確認）",
        "此頁涵蓋原表中送飯（D）、護送預留（ESC）、廚房（執牌）、其他工作及 OFF 標記。"
        "OFF 只代表表內如此標示，如另有意思請更正。",
        ncols,
    )
    row = _quick_confirm(ws, row, ncols)
    row = _header_row(ws, row, headers, reply_from=10)
    rows = [
        [
            u["kind"], u["weekday"], u["period"], u["worker"], u["raw_text"],
            u["time"] or u["notes"], u["place"], u["notes"] if u["time"] else "",
            u["source_cell"], "", "",
        ]
        for u in data["other_units"]
    ]
    _data_rows(ws, row, rows, reply_from=10, ncols=ncols)
    ws.auto_filter.ref = f"A{row-1}:{get_column_letter(ncols)}{row-1+len(rows)}"

    # --------------------------------------------------------- A5 skill matrix
    ws = wb.create_sheet("A5-技能記錄")
    aliases = [w["alias"] for w in data["skill_workers"]]
    headers = ["類別", "項目"] + aliases + ["備註"]
    _widths(ws, [12, 22] + [9] * len(aliases) + [22])
    ncols = len(headers)
    row = _title(
        ws, "A5　技能記錄（來自歷史「新同工跟服務紀錄表」，請確認）",
        "「✓」為原表已有的正向勾選，可先行確認；空白格代表原表未有記錄，"
        "並不代表該同工不會做——如實際可做，請直接在空白格補上「✓」。"
        "其餘 40 位同工原表沒有技能記錄，將於「B-需要提供的資料」一頁一併處理。",
        ncols,
    )
    row = _quick_confirm(ws, row, ncols)
    row = _header_row(ws, row, headers, reply_from=3)
    join_row = ["", "入職日期（原表）"] + [w["join_date_raw"] for w in data["skill_workers"]] + [""]
    _set(ws, row, 1, "", fill=F_PRE)
    _set(ws, row, 2, "入職日期（原表）", font=C_BODY_B, fill=F_PRE)
    for i, w in enumerate(data["skill_workers"]):
        _set(ws, row, 3 + i, w["join_date_raw"], fill=F_PRE, align=WRAP_C)
    _set(ws, row, ncols, "", fill=F_PRE)
    row += 1
    for entry in data["skill_matrix"]:
        _set(ws, row, 1, entry["category"], fill=F_PRE)
        _set(ws, row, 2, entry["item"], fill=F_PRE)
        for i, alias in enumerate(aliases):
            mark = entry["ticks"].get(alias, "")
            _set(ws, row, 3 + i, mark, fill=(F_PRE if mark else F_REPLY), align=WRAP_C)
        _set(ws, row, ncols, "", fill=F_REPLY)
        row += 1

    # ------------------------------------------------------------ A6 transfers
    ws = wb.create_sheet("A6-個案轉移紀錄")
    if data["transfers"]:
        src_headers = list(data["transfers"][0].keys())
    else:
        src_headers = []
    headers = src_headers + ["現況確認（已完成／已取消／更正）", "備註"]
    _widths(ws, [11] * len(src_headers) + [20, 14])
    ncols = len(headers)
    row = _title(
        ws, "A6　個案轉移紀錄（2025，預填，請確認現況）",
        "以下為原表「個案轉移紀錄_2025」的內容。部分標註 TBC 的安排，請確認最終結果。",
        ncols,
    )
    row = _quick_confirm(ws, row, ncols)
    row = _header_row(ws, row, headers, reply_from=len(src_headers) + 1)
    rows = []
    for t in data["transfers"]:
        values = []
        for h in src_headers:
            v = t.get(h, "")
            if isinstance(v, str) and v.endswith(" 00:00:00"):
                v = v[:-9]
            values.append(v)
        rows.append(values + ["", ""])
    _data_rows(ws, row, rows, reply_from=len(src_headers) + 1, ncols=ncols)

    # --------------------------------------------------------------- B provide
    ws = wb.create_sheet("B-需要提供的資料")
    headers = ["編號", "類別", "需要的資料", "為何需要", "最省力的回覆方式", "貴機構回覆", "備註"]
    _widths(ws, [7, 12, 40, 30, 34, 26, 14])
    ncols = len(headers)
    row = _title(
        ws, "B　需要提供的資料（文件中沒有記錄）",
        "以下項目在現有文件中沒有可靠記錄，需請貴機構提供。全部接受簡短文字、相片、截圖、"
        "WhatsApp／電郵、粵語錄音或短會議；毋須另行製表。可逐項在黃色欄回覆，"
        "亦可用一段錄音一次過交代多項。如暫未能確定，填「待確認」即可。",
        ncols,
    )
    row = _header_row(ws, row, headers, reply_from=6)
    miss_hours = "、".join(data["summary"]["workers_missing_hours"])
    miss_sat = "、".join(data["summary"]["workers_missing_saturday"])
    grey = "、".join(data["summary"]["workers_grey"])
    provide_items = [
        ("B01", "最新版本", "如貴機構持有較新版本的分工表、HC 時間表或護送總表，請直接提交最新原檔。",
         "避免以過期資料開始整理及試運行。", "直接提交原檔並註明「以此為準」；毋須逐行比較。"),
        ("B02", "同工名單", f"以下 9 位同工的原表沒有工作時間記錄：{miss_hours}。",
         "系統不應假設上下班時間。", "逐位填寫，或整體回覆「與一般同工相同＋例外」。"),
        ("B03", "同工名單", f"以下 7 位同工沒有星期六 A/B 組記錄：{miss_sat}。",
         "決定星期六可否安排工作。", "逐位填寫 A／B／不返星期六。"),
        ("B04", "同工名單", f"以下 6 位同工的欄位在原表以灰色顯示，現時在職狀態待確認：{grey}。",
         "灰色只代表待確認，不應直接當作已離職。", "逐位回覆在職／已離職／長期休假。"),
        ("B05", "同工名單", "各同工的性別；或只提供「哪些服務有性別要求＋涉及的同工」。",
         "PC、沖涼及部分護送可能有性別要求，資料未知時不能安全編排。", "名單加註，或只列出涉及性別要求的服務及人員。"),
        ("B06", "同工名單", "各同工所屬隊伍（原表只有部分同工有 HW／CC／AMC／MRC 等標籤）及全職／兼職。",
         "影響派工範圍及可用時間。", "在 A1 名單黃色欄補充，或口頭整體說明。"),
        ("B07", "服務技能", "各同工可承接的服務種類（E+RO、HC、PC、沖涼、ESC、中心、廚房、送飯等）。",
         "現時系統內的技能屬 Demo 假設，正式排班前必須由貴機構提供。",
         "強烈建議用快捷方式：「全部同工均可＋例外名單」或「只有以下同工可做某服務」；亦可錄音說明。"),
        ("B08", "送飯路線", "各同工熟悉／可承接的送飯路線（如灣仔1-3、柴灣1-2、小西灣、香、丘、雪華、寶珍等）。",
         "現時文件只有 6 位同工的歷史記錄，其他同工路線資格為零記錄。",
         "「全部路線均可＋例外」或按路線列名單；A5 頁空白格亦可直接補✓。"),
        ("B09", "長者要求", "哪些長者或服務有性別要求或其他人選要求。",
         "避免編排不合適的同工。", "只列出有要求的個案即可，其餘視為無特別要求。"),
        ("B10", "固定關係", "A2 頁「現時負責同工」中，哪些屬硬性指定（不可替換）、哪些只屬優先安排。",
         "人手調動時，系統需要知道哪些關係不可打破。", "整體回覆「全部屬優先安排＋例外」即可。"),
        ("B11", "中心規則", "AMC／MRC／GC 每半日正常需要人數、最低安全人數，及星期六／假期安排。",
         "A3 頁的觀察數字不等於要求數字。", "在 A3 頁黃色欄填寫，或錄音整體說明。"),
        ("B12", "崗位資格", "派藥、帶活動、清潔、主／協等崗位的資格要求及合資格同工名單（如需證書請註明）。",
         "避免編排未具資格的同工。", "現有證書表相片／截圖即可，或口述名單。"),
        ("B13", "日曆規則", "星期六 A/B 輪值的起點：請提供任何一個確定屬 A 更的星期六日期。",
         "有一個錨點日期即可推算全年。", "回覆一個日期即可，例如「2026-07-04 是 A 更」。"),
        ("B14", "週次規則", "「第 1、3 週」等週次的準確定義，以及「長周」「BL」等標記的意思。",
         "定義錯誤會令隔週服務落在錯的星期。", "文字說明，或提供一個實例（某服務在某月實際做了哪幾天）。"),
        ("B15", "假期安排", "公眾假期時，中心當值、送飯及上門服務如何處理。",
         "假期週的排班規則不同。", "按服務類別簡短說明一般做法。"),
        ("B16", "護送規則", "護送一般佔用多少時間？同一半日能否處理兩宗護送（例如同一醫院）？",
         "直接影響護送當日可否兼顧其他服務。", "一句話即可，例如「一般半日一宗，同院偶爾兩宗」。"),
        ("B17", "優先次序", "人手不足時各類服務的優先次序，以及哪些服務可改期／取消、哪些必須替補。",
         "系統在人手不足時只能按此建議，不會自行取捨。",
         "建議預設「所有取捨由排班負責人審批」；如有慣例請說明。"),
        ("B18", "代號含義", "以下代號／標籤的意思：HSS、MRCV、GCV、AMCV、V、CCSV、CC、(B)、(PT)、ED、HW，"
         "及送飯路線簡稱「香、丘、雪華、寶珍」的實際範圍。",
         "避免錯誤解讀原有表格。", "逐個一句話解釋即可；不確定可標待確認。"),
        ("B19", "實際案例", "3 個近期真實變動案例（請假、住院、取消、臨時護送等）：發生了甚麼、影響了哪些安排、最後如何處理。",
         "用真實案例核對我們對規則的理解。", "遮名 WhatsApp 截圖、幾句文字或 1-2 分鐘粵語錄音均可。"),
    ]
    for item in provide_items:
        values = list(item) + ["", ""]
        for idx in range(1, ncols + 1):
            fill = F_REPLY if idx >= 6 else F_PRE
            _set(ws, row, idx, values[idx - 1], fill=fill)
        row += 1
    row += 1
    _banner(
        ws, row, ncols,
        "首輪毋須處理：兩週試運行所需的當週 HC／護送資料、臨時變更記錄、人工排班結果及簽署，"
        "將於上述基礎資料確認後才另行安排，現階段毋須準備。",
        height=30, font=C_BODY,
    )

    wb.save(out_path)
    print(out_path)


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("Usage: build_confirmation_workbook.py DATA_JSON OUTPUT_XLSX")
    data = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    out = Path(sys.argv[2])
    out.parent.mkdir(parents=True, exist_ok=True)
    build(data, out)


if __name__ == "__main__":
    main()
