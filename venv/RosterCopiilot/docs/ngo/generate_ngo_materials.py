#!/usr/bin/env python3
"""Generate the NGO-facing RosterCopiilot PDF handover pack.

The documents intentionally use the macOS Songti TC typeface (a Song-style
Chinese font) and avoid relying on browser print output so pagination remains
stable and reviewable.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, Sequence

from reportlab.graphics.shapes import Drawing, Line as ShapeLine, Polygon
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    KeepTogether,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)


ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = ROOT / "output" / "pdf" / "ngo_handover_2026-07-19"
FONT_PATH = Path("/System/Library/Fonts/Supplemental/Songti.ttc")
TODAY = "2026-07-19"

NAVY = colors.HexColor("#173B57")
TEAL = colors.HexColor("#2B7C85")
PALE_BLUE = colors.HexColor("#EAF2F5")
PALE_GOLD = colors.HexColor("#F7F1E3")
PALE_RED = colors.HexColor("#F8E9E5")
PALE_GREEN = colors.HexColor("#EAF4ED")
INK = colors.HexColor("#24333D")
MUTED = colors.HexColor("#63717A")
LINE = colors.HexColor("#CBD5DA")
WHITE = colors.white


# TrueType conversions of Source Han Serif TC (思源宋體), produced from the
# system Noto Serif CJK TC by docs/ngo tooling; used when macOS Songti is absent.
FALLBACK_REGULAR = ROOT / "tmp" / "fonts" / "SongFallback-Regular.ttf"
FALLBACK_BOLD = ROOT / "tmp" / "fonts" / "SongFallback-Bold.ttf"


def register_song_fonts() -> None:
    """Register a Song-style CJK font: macOS Songti TC, otherwise Source Han Serif TC."""
    if "SongtiTC" in pdfmetrics.getRegisteredFontNames():
        return
    if FONT_PATH.exists():
        pdfmetrics.registerFont(TTFont("SongtiTC", str(FONT_PATH), subfontIndex=7))
        pdfmetrics.registerFont(TTFont("SongtiTC-Bold", str(FONT_PATH), subfontIndex=2))
    elif FALLBACK_REGULAR.exists():
        # Source Han Serif TC (思源宋體) — a Song-style serif typeface.
        pdfmetrics.registerFont(TTFont("SongtiTC", str(FALLBACK_REGULAR)))
        pdfmetrics.registerFont(TTFont("SongtiTC-Bold", str(FALLBACK_BOLD)))
    else:
        raise FileNotFoundError("No Song-style CJK font found (Songti.ttc / NotoSerifCJK)")
    if True:
        pdfmetrics.registerFontFamily(
            "SongtiTC",
            normal="SongtiTC",
            bold="SongtiTC-Bold",
            italic="SongtiTC",
            boldItalic="SongtiTC-Bold",
        )


def build_styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "cover_kicker": ParagraphStyle(
            "CoverKicker",
            parent=base["Normal"],
            fontName="SongtiTC-Bold",
            fontSize=10,
            leading=15,
            textColor=TEAL,
            spaceAfter=8,
        ),
        "cover_title": ParagraphStyle(
            "CoverTitle",
            parent=base["Title"],
            fontName="SongtiTC-Bold",
            fontSize=24,
            leading=34,
            textColor=NAVY,
            alignment=TA_LEFT,
            spaceAfter=12,
        ),
        "cover_subtitle": ParagraphStyle(
            "CoverSubtitle",
            parent=base["Normal"],
            fontName="SongtiTC",
            fontSize=12,
            leading=20,
            textColor=INK,
            spaceAfter=18,
        ),
        "h1": ParagraphStyle(
            "H1",
            parent=base["Heading1"],
            fontName="SongtiTC-Bold",
            fontSize=17,
            leading=24,
            textColor=NAVY,
            spaceBefore=8,
            spaceAfter=9,
            keepWithNext=True,
        ),
        "h2": ParagraphStyle(
            "H2",
            parent=base["Heading2"],
            fontName="SongtiTC-Bold",
            fontSize=13,
            leading=19,
            textColor=TEAL,
            spaceBefore=6,
            spaceAfter=6,
            keepWithNext=True,
        ),
        "body": ParagraphStyle(
            "Body",
            parent=base["BodyText"],
            fontName="SongtiTC",
            fontSize=10.2,
            leading=16,
            textColor=INK,
            spaceAfter=6,
        ),
        "body_compact": ParagraphStyle(
            "BodyCompact",
            parent=base["BodyText"],
            fontName="SongtiTC",
            fontSize=9.2,
            leading=13.5,
            textColor=INK,
            spaceAfter=3,
        ),
        "small": ParagraphStyle(
            "Small",
            parent=base["BodyText"],
            fontName="SongtiTC",
            fontSize=8.2,
            leading=11.5,
            textColor=INK,
        ),
        "small_white": ParagraphStyle(
            "SmallWhite",
            parent=base["BodyText"],
            fontName="SongtiTC-Bold",
            fontSize=8.4,
            leading=11.5,
            textColor=WHITE,
            alignment=TA_CENTER,
        ),
        "bullet": ParagraphStyle(
            "Bullet",
            parent=base["BodyText"],
            fontName="SongtiTC",
            fontSize=10,
            leading=15.5,
            textColor=INK,
            leftIndent=13,
            firstLineIndent=-9,
            bulletIndent=3,
            spaceAfter=4,
        ),
        "step_number": ParagraphStyle(
            "StepNumber",
            parent=base["Normal"],
            fontName="SongtiTC-Bold",
            fontSize=14,
            leading=18,
            textColor=WHITE,
            alignment=TA_CENTER,
        ),
        "table": ParagraphStyle(
            "Table",
            parent=base["BodyText"],
            fontName="SongtiTC",
            fontSize=8.6,
            leading=12.5,
            textColor=INK,
        ),
        "table_bold": ParagraphStyle(
            "TableBold",
            parent=base["BodyText"],
            fontName="SongtiTC-Bold",
            fontSize=8.6,
            leading=12.5,
            textColor=INK,
        ),
        "note": ParagraphStyle(
            "Note",
            parent=base["BodyText"],
            fontName="SongtiTC",
            fontSize=9.2,
            leading=14,
            textColor=INK,
            spaceAfter=0,
        ),
    }


STYLES: dict[str, ParagraphStyle]


class NGOPageTemplate(PageTemplate):
    def __init__(self, title: str):
        frame = Frame(
            18 * mm,
            18 * mm,
            A4[0] - 36 * mm,
            A4[1] - 38 * mm,
            leftPadding=0,
            rightPadding=0,
            topPadding=0,
            bottomPadding=0,
        )
        super().__init__(id="ngo", frames=[frame], onPage=self._draw_page)
        self.short_title = title

    def _draw_page(self, canvas, doc) -> None:
        canvas.saveState()
        canvas.setStrokeColor(LINE)
        canvas.setLineWidth(0.5)
        canvas.line(18 * mm, 13.5 * mm, A4[0] - 18 * mm, 13.5 * mm)
        canvas.setFont("SongtiTC", 7.8)
        canvas.setFillColor(MUTED)
        canvas.drawString(18 * mm, 9 * mm, self.short_title)
        canvas.drawRightString(
            A4[0] - 18 * mm,
            9 * mm,
            f"RosterCopiilot | {TODAY} | 第 {doc.page} 頁",
        )
        canvas.restoreState()


def doc_for(path: Path, title: str) -> BaseDocTemplate:
    doc = BaseDocTemplate(
        str(path),
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=20 * mm,
        bottomMargin=18 * mm,
        title=title,
        author="RosterCopiilot Project Team",
        subject="RosterCopiilot 資料移交文件",
        creator="RosterCopiilot PDF generator",
    )
    doc.addPageTemplates([NGOPageTemplate(title)])
    return doc


def para(text: str, style: str = "body") -> Paragraph:
    return Paragraph(text, STYLES[style])


def heading(text: str, level: int = 1) -> Paragraph:
    return para(text, "h1" if level == 1 else "h2")


def bullet(text: str, symbol: str = "•") -> Paragraph:
    return Paragraph(f"{symbol} {text}", STYLES["bullet"])


def bullets(items: Iterable[str], symbol: str = "•") -> list[Paragraph]:
    return [bullet(item, symbol=symbol) for item in items]


def compact_bullets(items: Iterable[str], symbol: str = "•") -> list[Paragraph]:
    style = ParagraphStyle(
        "CompactBullet",
        parent=STYLES["body_compact"],
        leftIndent=11,
        firstLineIndent=-8,
        bulletIndent=2,
        spaceAfter=2,
    )
    return [Paragraph(f"{symbol} {item}", style) for item in items]


def info_box(text: str, background=PALE_BLUE, border=TEAL) -> Table:
    box = Table([[para(text, "note")]], colWidths=[A4[0] - 36 * mm])
    box.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), background),
                ("BOX", (0, 0), (-1, -1), 0.8, border),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ]
        )
    )
    return box


def cover(
    kicker: str,
    title: str,
    subtitle: str,
    audience: str,
    status: str,
) -> list:
    return [
        Spacer(1, 22 * mm),
        para(kicker, "cover_kicker"),
        para(title, "cover_title"),
        para(subtitle, "cover_subtitle"),
        info_box(
            f"<b>適用對象：</b>{audience}<br/>"
            f"<b>文件狀態：</b>{status}<br/>"
            f"<b>版本日期：</b>{TODAY}",
            background=PALE_GOLD,
            border=colors.HexColor("#B79750"),
        ),
        Spacer(1, 12 * mm),
        para(
            "本文件使用宋體製作。請以 PDF 原檔閱讀或列印，避免由通訊軟件重新轉換後出現字型或分頁變化。",
            "small",
        ),
        PageBreak(),
    ]


def make_table(
    rows: Sequence[Sequence[str]],
    widths: Sequence[float],
    *,
    header: bool = True,
    font_size: float = 8.6,
    row_backgrounds: dict[int, colors.Color] | None = None,
) -> Table:
    table_style = ParagraphStyle(
        "DynamicTable",
        parent=STYLES["table"],
        fontSize=font_size,
        leading=font_size * 1.42,
    )
    header_style = ParagraphStyle(
        "DynamicHeader",
        parent=STYLES["small_white"],
        fontSize=font_size,
        leading=font_size * 1.35,
    )
    data = []
    for row_index, row in enumerate(rows):
        style = header_style if header and row_index == 0 else table_style
        data.append([Paragraph(str(cell).replace("\n", "<br/>"), style) for cell in row])
    table = Table(data, colWidths=list(widths), repeatRows=1 if header else 0)
    commands = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.35, LINE),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]
    if header:
        commands.append(("BACKGROUND", (0, 0), (-1, 0), NAVY))
    for row_index, background in (row_backgrounds or {}).items():
        commands.append(("BACKGROUND", (0, row_index), (-1, row_index), background))
    table.setStyle(TableStyle(commands))
    return table


def signature_table(labels: Sequence[str], *, compact: bool = False) -> Table:
    rows = []
    for label in labels:
        rows.append([para(f"<b>{label}</b>", "small"), para("________________________________________", "small")])
    table = Table(rows, colWidths=[42 * mm, A4[0] - 78 * mm])
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 3 if compact else 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3 if compact else 7),
            ]
        )
    )
    return table


def flatten_flowables(items: Iterable) -> list:
    """Flatten helper lists so section builders can embed bullet groups."""
    flattened = []
    for item in items:
        if isinstance(item, (list, tuple)):
            flattened.extend(flatten_flowables(item))
        else:
            flattened.append(item)
    return flattened


def step_block(number: int, title: str, text: str) -> Table:
    left = Table([[para(str(number), "step_number")]], colWidths=[12 * mm], rowHeights=[12 * mm])
    left.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), TEAL),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("BOX", (0, 0), (-1, -1), 0, TEAL),
            ]
        )
    )
    content = [para(f"<b>{title}</b>", "body_compact"), para(text, "body_compact")]
    right = Table([[content]], colWidths=[A4[0] - 52 * mm])
    right.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), PALE_BLUE),
                ("BOX", (0, 0), (-1, -1), 0.5, LINE),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    wrapper = Table([[left, right]], colWidths=[15 * mm, A4[0] - 51 * mm])
    wrapper.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    return wrapper


def handover_flow_step(
    number: int,
    title: str,
    organisation_text: str,
    project_text: str,
) -> Table:
    """Create one two-lane node in the NGO handover flow."""
    badge = Table(
        [[para(str(number), "step_number")]],
        colWidths=[12 * mm],
        rowHeights=[12 * mm],
    )
    badge.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), TEAL),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("BOX", (0, 0), (-1, -1), 0, TEAL),
            ]
        )
    )

    right_width = A4[0] - 51 * mm
    lane_width = right_width / 2
    node = Table(
        [
            [para(f"<b>{title}</b>", "small_white"), ""],
            [para("<b>貴機構</b>", "table_bold"), para("<b>本項目團隊</b>", "table_bold")],
            [para(organisation_text, "small"), para(project_text, "small")],
        ],
        colWidths=[lane_width, lane_width],
    )
    node.setStyle(
        TableStyle(
            [
                ("SPAN", (0, 0), (-1, 0)),
                ("BACKGROUND", (0, 0), (-1, 0), NAVY),
                ("BACKGROUND", (0, 1), (-1, 1), PALE_BLUE),
                ("ALIGN", (0, 0), (-1, 0), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("GRID", (0, 1), (-1, -1), 0.35, LINE),
                ("BOX", (0, 0), (-1, -1), 0.6, NAVY),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )

    wrapper = Table([[badge, node]], colWidths=[15 * mm, right_width])
    wrapper.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    return wrapper


def flow_arrow() -> Drawing:
    """Return a compact vector arrow between handover flow nodes."""
    width = A4[0] - 36 * mm
    height = 5.5 * mm
    centre = width / 2
    arrow = Drawing(width, height)
    arrow.add(
        ShapeLine(
            centre,
            height,
            centre,
            2.2 * mm,
            strokeColor=TEAL,
            strokeWidth=1.4,
        )
    )
    arrow.add(
        Polygon(
            [
                centre - 1.8 * mm,
                2.5 * mm,
                centre + 1.8 * mm,
                2.5 * mm,
                centre,
                0.4 * mm,
            ],
            fillColor=TEAL,
            strokeColor=TEAL,
        )
    )
    return arrow


def build_confirmation_checklist(path: Path) -> None:
    story = cover(
        "資料移交文件 01",
        "排班資料移交指南",
        "本項目團隊已根據貴機構先前提供的文件，把可讀取的資料預先整理並填入隨附的《排班資料確認冊》。"
        "貴機構毋須由零開始提供資料：只需確認預填內容、補充文件未有記錄的少量項目。",
        "排班負責人、中心主管、資料負責同工",
        "首輪確認及補充之用；格式從寬，資料齊全比格式整齊重要",
    )
    story += [
        heading("本套材料清單"),
        para("本指南連同以下文件一併送上。建議先閱讀本指南第一、二節，再打開確認冊。"),
        make_table(
            [
                ["文件", "內容", "貴機構需要做的事"],
                ["01 排班資料移交指南（本文件）", "說明整體安排、確認方式及需要補充的資料。", "閱讀第一、二節即可開始。"],
                ["02 排班資料確認冊（Excel）", "我們已預填的同工、服務、當值等資料，以及需要補充的項目清單。", "確認及補充（詳見第三、四節）。"],
                ["03 Demo 使用手冊", "排班系統 Demo 的操作步驟。", "留待示範時參考，毋須先讀。"],
                ["04 私隱與資料處理說明", "資料最小化、保存及存取原則。", "供管理層及資料負責人審閱。"],
                ["05 兩週平行試運行與簽署表", "試運行階段的流程及簽署頁。", "後續階段才使用，首輪毋須理會。"],
            ],
            [52 * mm, 72 * mm, 49 * mm],
            font_size=8.4,
        ),
        Spacer(1, 4 * mm),
        heading("目錄", 2),
        make_table(
            [
                ["節", "內容", "頁碼"],
                ["一、整體安排", "資料分為三類；五項省力原則。", "3"],
                ["二、雙方如何完成移交", "四步流程圖及雙方分工。", "4"],
                ["三、請確認的資料（甲類）", "確認冊各頁內容及最快的確認方法。", "5"],
                ["四、請提供的資料（乙類）", "文件沒有記錄、需要貴機構提供的項目。", "6"],
                ["五、稍後才需要（丙類）", "試運行階段的資料，首輪毋須準備。", "7"],
                ["六、提交方式與檢查", "可接受格式、提交前檢查及聯絡方法。", "7"],
            ],
            [46 * mm, 107 * mm, 20 * mm],
            font_size=8.6,
        ),
        PageBreak(),
        heading("一、整體安排：資料分為三類"),
        para(
            "本指南的目的只有一個：以最少的工作量，把排班所需的資料確定下來。"
            "為此，我們把所有資料分為三類，每類的處理方式不同："
        ),
        Spacer(1, 2 * mm),
        make_table(
            [
                ["類別", "定義", "貴機構需要做的事"],
                ["甲類：請確認",
                 "我們已從現有文件整理或推斷出來，並已預先填入確認冊。",
                 "整頁無誤時只需填「確認無誤」；有少量差異時只填例外；暫未能確定可標「待確認」。"],
                ["乙類：請提供",
                 "現有文件中沒有可靠記錄，我們無法代填。",
                 "以任何方便的形式提供（文字、相片、截圖、錄音均可），整理由我們負責。"],
                ["丙類：稍後才需要",
                 "兩週試運行時才需要的資料。",
                 "首輪毋須準備，屆時另行約定。"],
            ],
            [30 * mm, 65 * mm, 78 * mm],
            font_size=8.4,
        ),
        Spacer(1, 4 * mm),
        heading("五項省力原則", 2),
        compact_bullets(
            [
                "<b>毋須逐行重抄：</b>預填內容整體正確時，只需在該頁頂部填「確認無誤」；只有少量差異時，只需在相關行填寫更正。",
                "<b>最新原檔優先：</b>如貴機構持有更新版本的文件，可直接提交最新原檔並註明「以此為準」，毋須自行逐行比較、合併或清理。",
                "<b>任何格式均可：</b>Excel、Word、PDF、相片、截圖、WhatsApp／電郵文字、粵語錄音或短會議均可；轉錄、去重及格式統一由本項目團隊負責。",
                "<b>容許未知：</b>任何一項暫時無法確定，填「待確認／不適用／暫未掌握」即可，毋須猜測，亦毋須因少量缺口延遲其餘資料。",
                "<b>不重複索取：</b>我們已掌握的資料不會要求貴機構重新提供；確認冊中空白的格，代表文件確實沒有記錄。",
            ],
            symbol="•",
        ),
        Spacer(1, 4 * mm),
        info_box(
            "<b>例：</b>確認冊「A2-恆常服務」共 370 行。如其中只有一行的時間有變，"
            "貴機構只需在該行的黃色欄填寫「時間應為 9:00-10:30」，並在頁頂填「其餘確認無誤」。"
            "全程需要書寫的只有一句。",
            background=PALE_GREEN,
            border=TEAL,
        ),
        PageBreak(),
        heading("二、雙方如何完成移交"),
        para("整個移交按以下四步進行；每步左欄為貴機構的部分，右欄為本項目團隊的部分。"),
        Spacer(1, 2 * mm),
        handover_flow_step(
            1,
            "我們送上預填材料（本套文件）",
            "接收本指南及確認冊；如持有更新版文件，可先行提交原檔。",
            "已完成資料整理及預填；空白格代表文件沒有記錄。",
        ),
        flow_arrow(),
        handover_flow_step(
            2,
            "貴機構確認甲類、提供乙類",
            "逐頁快速確認；只填例外；乙類項目以任何方便形式回覆。",
            "解答疑問；如需要可安排一次短會議代替書面回覆。",
        ),
        flow_arrow(),
        handover_flow_step(
            3,
            "我們整理並回送核對摘要",
            "毋須動手；等候摘要。",
            "轉錄錄音、整理回覆、更新資料，並列出仍然存疑的少數項目。",
        ),
        flow_arrow(),
        handover_flow_step(
            4,
            "雙方確認後，約定試運行",
            "核對摘要，確認或再更正；之後才開始丙類（試運行）安排。",
            "凍結已確認資料版本，準備兩週平行試運行。",
        ),
        PageBreak(),
        heading("三、請確認的資料（甲類）"),
        para(
            "以下內容已預先填入《排班資料確認冊》。每頁頂部均有「整頁快速確認」格；"
            "灰色底為我們預填的內容，黃色底為請貴機構填寫的位置。"
        ),
        Spacer(1, 2 * mm),
        make_table(
            [
                ["確認冊頁面", "已預填的內容", "請特別留意"],
                ["A1-同工名單（46 位）",
                 "同工代號、原表標籤、原表工作時間、星期六 A/B 組別、推定狀態。",
                 "灰色欄位的 6 位同工只屬「狀態待確認」，並非我們認定已離職；空白代表原表沒有記錄。"],
                ["A2-恆常服務（370 項）",
                 "長者代號、單位、服務原文、星期、上／下午、時間、週次、現時負責同工及表內備註。",
                 "「現時負責同工」暫按目前安排理解；屬硬性指定者請註明「硬性」。"],
                ["A3-中心當值（36 個時段）",
                 "AMC／MRC／GC 每半日在表內出現的當值同工及角色標註。",
                 "表內人數只屬觀察所得，請另補正常需要及最低安全人數。"],
                ["A4-送飯、護送、廚房及其他（277 項）",
                 "送飯（D）、護送預留（ESC）、廚房（執牌）、其他工作及 OFF 標記的現有安排。",
                 "OFF 只代表表內如此標示，如另有意思請更正。"],
                ["A5-技能記錄（6 位同工）",
                 "歷史「新同工跟服務紀錄表」中的正向勾選（✓）。",
                 "空白格代表「未有記錄」而非「不會做」；可直接補✓。"],
                ["A6-個案轉移紀錄（9 項）",
                 "2025 年轉移紀錄，含標註 TBC 的安排。",
                 "請確認各項現況：已完成、已取消或另有更正。"],
            ],
            [42 * mm, 68 * mm, 63 * mm],
            font_size=8.2,
        ),
        Spacer(1, 3 * mm),
        info_box(
            "此外，確認冊亦載有我們對服務代號（E+RO、HC、PC、B、ESC、D 等）、時段、週次及固定同工關係的理解，"
            "已按「需要確認」逐項列出；如整體正確，同樣可一次過確認。",
            background=PALE_BLUE,
            border=TEAL,
        ),
        PageBreak(),
        heading("四、請提供的資料（乙類）"),
        para(
            "以下項目在現有文件中沒有可靠記錄。完整清單連同回覆欄已載於確認冊「B-需要提供的資料」頁，"
            "此處按類別撮要。每項均可用簡短文字或錄音回覆。"
        ),
        Spacer(1, 2 * mm),
        make_table(
            [
                ["類別", "需要的資料", "最省力的回覆方式"],
                ["名單缺口",
                 "9 位同工的工作時間、7 位的星期六組別、6 位灰色欄同工的在職狀態；性別、所屬隊伍及全職／兼職。",
                 "逐位一句話，或「與一般相同＋例外」。"],
                ["服務資格",
                 "各同工可承接的服務種類及送飯路線（現時系統內的技能屬 Demo 假設，必須取代）。",
                 "「全部均可＋例外名單」，或按服務／路線列名單；錄音亦可。"],
                ["中心規則",
                 "各中心每半日正常需要及最低安全人數；派藥、帶活動、清潔、主／協的資格要求及合資格名單。",
                 "在確認冊 A3 頁補數字；證書表相片即可。"],
                ["日曆與規則",
                 "星期六 A/B 起點（一個確定屬 A 更的日期）、週次定義、「長周」「BL」等標記、公眾假期安排。",
                 "各一句話或一個實例。"],
                ["護送與優先次序",
                 "護送一般佔用時間、同半日可否兩宗；人手不足時的優先次序及可改期／取消的服務。",
                 "一句話；或採用預設「所有取捨由排班負責人審批」。"],
                ["代號含義",
                 "HSS、MRCV、GCV、V、CC、(B)、(PT)、ED 等標籤，及「香、丘、雪華、寶珍」等路線簡稱的意思。",
                 "逐個一句話；不確定可標待確認。"],
                ["實際案例",
                 "3 個近期真實變動案例（請假、住院、取消、臨時護送等）及當時的處理方法。",
                 "遮名截圖、幾句文字或 1-2 分鐘粵語錄音。"],
            ],
            [28 * mm, 90 * mm, 55 * mm],
            font_size=8.2,
        ),
        Spacer(1, 3 * mm),
        heading("一段錄音可以同時回覆多項", 2),
        info_box(
            "「AMC 平日上晝通常 3 個人，最少唔可以少過 2 個，其中 1 個要識派藥。星期六唔開。"
            "護送通常當半日，同一間醫院有時可以一個人跟兩單。所有同工都做到 HC，除咗阿 A 同阿 B。」<br/><br/>"
            "以上述形式說明即可，本項目團隊會整理成文字，再交回貴機構核對。",
            background=PALE_GOLD,
            border=colors.HexColor("#B79750"),
        ),
        PageBreak(),
        heading("五、稍後才需要的資料（丙類）"),
        para(
            "兩週平行試運行所需的資料——包括實際週次的選定、當週 HC 及護送資料、臨時變更記錄、"
            "貴機構人工排班結果、差異確認及簽署——將於上述甲、乙兩類資料確認後才另行約定。"
            "首輪毋須準備，文件 05 屆時才會用到。"
        ),
        Spacer(1, 5 * mm),
        heading("六、提交方式與檢查"),
        info_box(
            "<b>可接受格式：</b>Excel、Word、PDF、相片、截圖、掃描、WhatsApp／電郵文字、粵語錄音或短會議均可。"
            "原檔優先；不方便改名或整理也可以直接提交。",
            background=PALE_GREEN,
            border=TEAL,
        ),
        Spacer(1, 4 * mm),
        heading("提交前一分鐘檢查", 2),
        compact_bullets(
            [
                "□ 確認冊 A1 至 A6 各頁已「整頁確認」或已填寫例外。",
                "□ 「B-需要提供的資料」各項已回覆，或已標「待確認」。",
                "□ 如持有更新版文件，已一併提交並註明「以此為準」。",
                "□ 已指定一位熟悉排班的核對人及最方便的聯絡方式。",
            ],
            symbol="",
        ),
        Spacer(1, 4 * mm),
        signature_table(
            [
                "貴機構核對人",
                "最方便聯絡方式",
                "首輪提交日期",
                "項目團隊接收人",
            ],
            compact=True,
        ),
    ]
    doc_for(path, "排班資料移交指南").build(flatten_flowables(story))


def build_demo_manual(path: Path) -> None:
    story = cover(
        "資料移交文件 03",
        "RosterCopiilot Demo 使用手冊",
        "按現行示範頁面編寫：由上載本週需求、生成排班草稿、逐項人工審核，到發佈及下載正式版 Excel 的完整操作指引。",
        "貴機構排班同工、主管及觀察員",
        "Demo 示範使用；不等同正式上線或自動發放",
    )
    story += [
        heading("1. Demo 能做甚麼"),
        para(
            "RosterCopiilot 是確定性的自動排班草稿工具。系統根據內置固定分工基礎、目標週的 HC 及護送需求"
            "以及臨時變更提出草稿，再由主管逐項審核。系統不會取代主管決定，也不會自動把文件發送給同工或長者。",
        ),
        make_table(
            [
                ["每次使用需要上載", "系統已內置，毋須上載"],
                ["HC 時間表工作簿：家居清潔、個人照顧、沖涼及 HC 表中的其他服務需求。", "照顧員工作分工表：固定分工基礎及輸出格式。"],
                ["護送個案總表工作簿：護送日期、時段、目的地、科目及備註偏好。", "已保存的基礎資料及既有固定安排。"],
            ],
            [86.5 * mm, 86.5 * mm],
        ),
        Spacer(1, 5 * mm),
        info_box(
            "<b>重要：</b>請使用同一個目標週的 HC 和護送資料。目前示範樣本的 HC 屬 2026 年 5 月、護送屬 2026 年 1 月；"
            "系統會按目標週真實篩選，不會補造不在該週的需求，因此兩份樣本不能假裝屬於同一週。",
            background=PALE_GOLD,
            border=colors.HexColor("#B79750"),
        ),
        Spacer(1, 6 * mm),
        heading("2. 畫面總覽"),
        para("示範頁面為單一頁，分左右兩欄。開始前，請先認住以下位置："),
        make_table(
            [
                ["位置", "內容"],
                ["頁面頂部", "三個狀態徽章：後端連線狀態（應顯示綠色「後端已連線」）、「固定基礎：內置」，以及生成狀態（由「尚未生成」變為「生成中」，完成後顯示發放狀態）。"],
                ["左欄「四步生成」", "步驟 1 上載 HC 時間表；步驟 2 上載護送總表；步驟 3 選擇目標週與臨時變更；步驟 4 生成、下載及發佈按鈕。"],
                ["右欄「生成結果」", "六格數字摘要、總排班預覽、臨時變更影響、未分配任務及審核項目清單。"],
                ["頁底「開發工具」", "「重新檢查後端」及「檢查內置樣本」，供項目團隊驗證用；貴機構一般毋須使用。"],
            ],
            [30 * mm, 143 * mm],
            font_size=8.4,
        ),
        PageBreak(),
        heading("3. 操作步驟"),
        step_block(1, "檢查後端連線", "確認頁面頂部顯示綠色「後端已連線」。如顯示紅色「後端未連線」，請勿繼續，先聯絡項目團隊；可在頁底「開發工具」按「重新檢查後端」重試。"),
        Spacer(1, 3 * mm),
        step_block(2, "上載 HC 時間表", "在步驟一選擇該週的 HC 時間表工作簿（.xlsx 或 .xlsm）。請使用原檔複製本，不要改工作表名稱或刪除標題行。"),
        Spacer(1, 3 * mm),
        step_block(3, "上載護送總表", "在步驟二選擇該週的護送個案總表工作簿。不要上載固定分工表——固定基礎已內置。"),
        Spacer(1, 3 * mm),
        step_block(4, "選擇目標週", "在「目標週星期一」選擇日期。選了其他日子時，頁面會自動對齊至該週星期一並提示；請核對顯示的日期。"),
        Spacer(1, 3 * mm),
        step_block(5, "加入臨時變更（如有）", "在「臨時變更」下拉選單選擇：不加入、新增護送、同工請假或長者取消服務，再按類型填寫同工短名／長者短名／目的地／科目及備註。示範版每次生成只附一項變更。按「填入樣本週」可自動填入 2026 年 1 月樣本資料。"),
        Spacer(1, 3 * mm),
        step_block(6, "生成排班表", "按「生成排班表」。頂部徽章會顯示「生成中」，完成後顯示發放狀態；期間不要重複按鍵。如顯示「生成失敗」，請把提示訊息截圖交項目團隊。"),
        Spacer(1, 3 * mm),
        step_block(7, "閱讀生成結果", "先看右欄六格數字：固定基礎同工欄、目標週 HC 需求、目標週護送需求、可落格項目、未分配項目、審核項目。再看「總排班預覽」（最多預覽首 26 項，完整內容以下載的 Excel 為準）。"),
        Spacer(1, 3 * mm),
        step_block(8, "逐項處理審核項目", "在「審核項目」清單逐項決定：先填「審核人」，再按「批准」「修改」或「拒絕」（詳見第 4 節）。完成一批決定後，可按「重新驗證」由伺服器更新狀態及總數。"),
        Spacer(1, 3 * mm),
        step_block(9, "下載審核草稿", "按「下載審核草稿」取得並行檢查 Excel（檔名：照顧員工作分工表_審核草稿.xlsx）。此檔仍是草稿，未經主管確認不可當正式更表發放。"),
        Spacer(1, 3 * mm),
        step_block(10, "發佈及下載正式版", "只有伺服器狀態為「可發放」時，「發佈正式版」才會啟用。填寫「正式版發佈人」（主管姓名或工作電郵）後按「發佈正式版」，再按「下載正式版」（檔名：照顧員工作分工表_正式版.xlsx）。重複發佈會載入同一份不可變正式版，不會產生第二個版本。"),
        Spacer(1, 5 * mm),
        heading("4. 如何處理審核項目"),
        para("每張審核卡片會顯示類型（如替補建議、未分配工作、中心當值不足、資料缺口等）、原因及狀態（阻塞或待審核）。操作前必須填寫「審核人」。"),
        make_table(
            [
                ["操作", "何時使用", "必須填寫", "結果"],
                ["批准", "同意系統提出的明確建議。如按鈕呈灰色，代表此項沒有可批准建議，請改用修改或補充資料。", "審核人。", "產生新的已審核版本，並自動重新驗證。"],
                ["修改", "主管要指定不同安排。按「修改」展開欄位：同工編號（必填）、日期、時段、節次。", "審核人、備註；如違反硬規則，還須填「覆核說明」。", "儲存人工修改版本；硬規則仍違反時保持不可發放。"],
                ["拒絕", "不同意建議。", "審核人及備註。", "需求回到安全狀態，不會被靜默刪除，並保留記錄。"],
                ["重新驗證", "完成一批決定後，或懷疑頁面資料過期。", "毋須填寫。", "按伺服器保存版本重新驗證；穩定編號及總數不變，不會重跑排班。"],
            ],
            [22 * mm, 62 * mm, 44 * mm, 45 * mm],
            font_size=8.2,
        ),
        Spacer(1, 4 * mm),
        info_box(
            "不要為了得到綠色狀態而刪除未分配、資料缺口或審核項目。覆核說明會保留責任記錄，但不能豁免硬規則，"
            "也不能把違規版本變成「可發放」。",
            background=PALE_RED,
            border=colors.HexColor("#B45F4A"),
        ),
        Spacer(1, 5 * mm),
        heading("5. 三種發放狀態"),
        make_table(
            [
                ["頁面狀態", "意思", "可以做甚麼"],
                ["可發放", "沒有硬規則、未分配、阻塞審核或來源對賬問題。", "由具名發佈人執行獨立正式發佈。"],
                ["草稿需審核", "沒有阻塞項，但仍有非阻塞審核或不確定資料。", "繼續審核；可下載明確標識的審核草稿。"],
                ["不可發放", "仍有硬規則、未分配、阻塞審核或匯出問題。", "只可作並行審核材料，不可給同工當正式更表。"],
            ],
            [32 * mm, 88 * mm, 53 * mm],
            row_backgrounds={1: PALE_GREEN, 2: PALE_GOLD, 3: PALE_RED},
        ),
        PageBreak(),
        heading("6. 下載後怎樣看 Excel"),
        make_table(
            [
                ["工作表", "用途"],
                ["恆常服務", "按貴機構原有格式顯示排班草稿；新增或變更格位附有標記和批注。"],
                ["RC_變更摘要", "目標週、上載資料、臨時變更及本次生成摘要。"],
                ["RC_審核", "所有審核項目、編號、原因、來源及處理狀態。"],
                ["RC_未分配", "無法安全安排或無法落格的項目、原因和建議處置。"],
                ["RC_meta", "版本、來源、發放狀態、寫入統計及對賬資料。"],
            ],
            [43 * mm, 130 * mm],
        ),
        Spacer(1, 5 * mm),
        bullets(
            [
                "審核草稿檔名：照顧員工作分工表_審核草稿.xlsx；正式版檔名：照顧員工作分工表_正式版.xlsx。",
                "需要覆核的格位批注以 RC:待審 開始，並列出審核、需求、安排及來源編號。",
                "原有業務顏色、邊框及批注會保留；系統只追加自己的標記。",
            ]
        ),
        heading("7. 常見問題"),
        make_table(
            [
                ["情況", "處理方法"],
                ["頂部顯示「後端未連線」", "不要繼續上載；按「開發工具」內「重新檢查後端」重試，仍失敗請截圖並通知項目團隊。"],
                ["目標週日期自動跳走", "屬正常：系統會把所選日期對齊至該週星期一，並彈出提示。"],
                ["HC 或護送需求數字為 0", "多數因上載檔案的日期不在目標週內；請核對目標週和 Excel 日期，不要人手補造需求。"],
                ["「批准」按鈕呈灰色", "此項沒有可批准的明確建議；請改用「修改」指定安排，或補充資料後重新生成。"],
                ["「下載審核草稿」不可按", "本次生成未通過匯出前檢查；請閱讀頁面列出的原因，完成審核後按「重新驗證」。"],
                ["「發佈正式版」不可按", "只有伺服器重新驗證為「可發放」時才會啟用，這是安全設計；請先處理阻塞項目。"],
                ["發現系統與人工安排不同", "不要直接刪改審核記錄；記下差異，交由排班負責人分類（試運行階段有專用差異表）。"],
            ],
            [48 * mm, 125 * mm],
            font_size=8.4,
        ),
        PageBreak(),
        heading("8. 每次示範結束前"),
        bullets(
            [
                "確認所有資料缺口、未分配和審核項目都已閱讀。",
                "記錄批次編號（頁面「生成結果」標題下方顯示）、目標週及使用的檔案版本。",
                "保存審核草稿及人工更表，供平行比較。",
                "如已發佈正式版，記錄發佈人、時間及正式版檔案。",
                "不要把「審核草稿」改名為「正式版」。",
                "按貴機構資料處理規定保存或刪除本次使用的檔案。",
            ],
            symbol="□",
        ),
        Spacer(1, 8 * mm),
        heading("9. 支援記錄"),
        signature_table(
            [
                "貴機構使用者",
                "示範日期／目標週",
                "批次編號／版本",
                "遇到的問題",
                "項目團隊跟進人",
                "跟進日期",
            ]
        ),
    ]
    doc_for(path, "RosterCopiilot Demo 使用手冊").build(flatten_flowables(story))


def week_signoff_section(week_number: int) -> list:
    return [
        heading(f"試運行第 {week_number} 週記錄", 1),
        signature_table(
            [
                "目標週星期一",
                "輸入截止時間",
                "人工更表版本／證據編號",
                "系統 Run ID／版本",
                "差異表版本",
                "排班負責人",
            ]
        ),
        Spacer(1, 4 * mm),
        make_table(
            [
                ["檢查項目", "完成", "備註／證據"],
                ["該週 HC、護送、固定基礎及臨時變化已凍結並記錄版本。", "□", ""],
                ["貴機構人工編制排班已完成，並作為該週業務基準。", "□", ""],
                ["系統草稿已生成；所有需求均有明確處置。", "□", ""],
                ["審核、未分配及資料缺口均逐項閱讀。", "□", ""],
                ["系統與人工更表的每個差異均已分類。", "□", ""],
                ["沒有未分類差異；沒有仍屬 blocking 的差異。", "□", ""],
                ["工程檢查 和比較檢查 的結果已附上。", "□", ""],
            ],
            [112 * mm, 18 * mm, 43 * mm],
            font_size=8.4,
        ),
        Spacer(1, 5 * mm),
        make_table(
            [
                ["差異分類", "數量", "排班負責人說明"],
                ["expected：已知且符合雙方預期", "", ""],
                ["reviewer_approved：主管保留人工決定", "", ""],
                ["blocking：必須修正後才可通過", "", ""],
                ["uncategorized：尚未分類，不可簽署", "", ""],
            ],
            [65 * mm, 25 * mm, 83 * mm],
        ),
        Spacer(1, 5 * mm),
        info_box(
            "<b>本週結論：</b>□ 通過比較　□ 有阻塞，需重做　□ 資料不完整，暫停簽署",
            background=PALE_GOLD,
            border=colors.HexColor("#B79750"),
        ),
        Spacer(1, 5 * mm),
        signature_table(
            [
                "排班負責人簽署／內部代號",
                "簽署時間",
                "簽署證據編號",
                "項目團隊覆核人",
            ]
        ),
    ]


def build_parallel_signoff(path: Path) -> None:
    story = cover(
        "資料移交文件 05",
        "兩週平行試運行與簽署表",
        "在不取代現行人工排班的前提下，記錄兩個真實星期的輸入、差異、決定及排班負責人簽署。",
        "貴機構排班負責人、中心主管、項目團隊",
        "後續試運行階段才使用；首輪毋須填寫",
    )
    story += [
        heading("1. 試運行目的"),
        para(
            "平行試運行期間，貴機構人工編制的排班表仍是唯一業務基準。RosterCopiilot 只產生獨立草稿，用於檢查是否完整、可解釋及符合實際規則。不得把系統草稿直接派發給員工。",
        ),
        info_box(
            "完成兩週簽署是本階段驗收的必要條件，但只證明這兩個星期的比較證據完整；不等於長期上線批准，也不取消每週的人手審核和 ready-only 發佈。",
            background=PALE_RED,
            border=colors.HexColor("#B45F4A"),
        ),
        Spacer(1, 5 * mm),
        heading("2. 開始前條件"),
        bullets(
            [
                "貴機構已確認同工技能、性別、路線、可用時間、長者要求及中心當值規則，並提供證據編號。",
                "選定兩個不同、真實、以星期一開始的星期；兩週均有真實 HC、護送及人工更表。",
                "指定一名排班負責人負責差異分類和最終簽署。",
                "項目團隊準備系統 run、逐格比較及差異記錄；不從人工表空格推斷新需求。",
                "雙方約定資料截止、文件命名、保存位置及私隱處理方式。",
            ],
            symbol="□",
        ),
        heading("3. 每週流程"),
        make_table(
            [
                ["步驟", "貴機構", "項目團隊"],
                ["1. 凍結輸入", "確認 HC、護送、臨時變化及人工更表版本。", "記錄來源版本和目標週。"],
                ["2. 獨立生成", "繼續按現行方式完成人工排班。", "使用相同截止資料生成系統草稿。"],
                ["3. 逐格比較", "解釋業務差異及人工決定。", "列出 exact cell、處置和來源差異。"],
                ["4. 分類差異", "把每項分為 expected、reviewer approved 或 blocking。", "檢查沒有遺漏、重複或過期差異。"],
                ["5. 解決阻塞", "補資料或確認規則。", "修正技術問題並重新生成／比較。"],
                ["6. 簽署", "確認無未分類及 blocking 差異後簽署。", "保存比較報告、證據編號和簽署時間。"],
            ],
            [25 * mm, 72 * mm, 76 * mm],
            font_size=8.3,
        ),
        PageBreak(),
    ]
    story += week_signoff_section(1)
    story += [PageBreak()]
    story += week_signoff_section(2)
    story += [
        PageBreak(),
        heading("兩週總結與驗收"),
        make_table(
            [
                ["總結項目", "第 1 週", "第 2 週", "整體"],
                ["工程檢查", "□ 通過", "□ 通過", "□"],
                ["比較檢查", "□ 通過", "□ 通過", "□"],
                ["未分類差異", "____", "____", "必須為 0"],
                ["blocking 差異", "____", "____", "必須為 0"],
                ["排班負責人已簽署", "□", "□", "兩週均需要"],
                ["基礎資料證據完整", "", "", "□"],
            ],
            [70 * mm, 32 * mm, 32 * mm, 39 * mm],
        ),
        Spacer(1, 6 * mm),
        heading("證據包清單", 2),
        bullets(
            [
                "已確認基礎資料的版本和證據編號。",
                "兩個星期的系統 run 記錄及版本／內容 hash。",
                "兩個星期的 貴機構人工工作簿。",
                "兩個星期的逐項差異表和處置比較。",
                "兩份本表的排班負責人簽署記錄。",
                "任何仍未解決的風險、限制及上線前條件。",
            ],
            symbol="□",
        ),
        Spacer(1, 5 * mm),
        info_box(
            "<b>驗收結論：</b>□ 通過　□ 待定　□ 受阻<br/>"
            "只有基礎資料有真實證據、兩週均簽署、工程及比較通過、未分類和 blocking 差異均為 0 時，才可填寫「通過」。",
            background=PALE_GREEN,
            border=TEAL,
        ),
        Spacer(1, 6 * mm),
        signature_table(
            [
                "貴機構排班負責人",
                "貴機構管理層／主管",
                "項目團隊負責人",
                "總結日期",
                "證據包位置／編號",
                "未解決條件",
            ]
        ),
    ]
    doc_for(path, "兩週平行試運行與簽署表").build(flatten_flowables(story))


def build_privacy_note(path: Path) -> None:
    story = cover(
        "資料移交文件 04",
        "私隱與資料處理說明",
        "Demo 及兩週試運行期間的資料最小化、存取、保存和文件分發原則。",
        "貴機構管理層、資料負責人、排班同工及項目團隊",
        "供討論及簽認；實際部署前需由貴機構確認內部政策",
    )
    story += [
        heading("1. 核心承諾", 2),
        compact_bullets(
            [
                "排班、資格檢查、修復、審核狀態和發佈決定均為確定性規則流程，不使用 LLM。",
                "Demo 只應使用代號或化名；毋須把真實長者姓名交給項目團隊。",
                "系統不會自動把排班表發送給員工、長者、WhatsApp 或 Google Drive。",
                "未知資料不會由系統猜測，會顯示為資料缺口、待審核、未分配或不可發放。",
                "只有具名人員在伺服器顯示「可發放」時，才能執行獨立正式發佈。",
            ],
            symbol="•",
        ),
        heading("2. Demo 會處理的資料", 2),
        make_table(
            [
                ["資料", "用途", "最小化要求"],
                ["同工代號、技能、性別、路線及可用時間", "資格和衝突檢查", "只填排班所需欄位；不填身份證、電話或住址。"],
                ["長者代號、服務、時段、地區及性別要求", "產生每週需求", "使用穩定代號；不填真實姓名或完整地址。"],
                ["HC、護送及臨時變化", "目標週排班", "只提供相關日期、服務和必要備註。"],
                ["審核人、發佈人及決定記錄", "責任追蹤和版本歷史", "可使用貴機構內部代號，但必須能由貴機構自行追溯。"],
            ],
            [35 * mm, 50 * mm, 88 * mm],
            font_size=8.2,
        ),
        Spacer(1, 4 * mm),
        heading("3. 保存與存取", 2),
        para(
            "目前 Demo 會保存規範化的每週 run、版本、審核決定和發佈記錄，以便重啟後繼續審核和證明來源。原始上載文件不需要作為長期 run 資料保存。實際保存位置、備份、保留期限、刪除流程和管理員名單，必須由貴機構在試運行前確認。",
            "body_compact",
        ),
        compact_bullets(
            [
                "□ 運行位置：中心指定電腦／貴機構伺服器／其他：________________",
                "□ 可上載人員：________________　可審核人員：________________",
                "□ 可發佈正式版人員：________________　系統管理員：________________",
                "□ Run 及審核記錄保存期限：________________",
                "□ 上載文件及導出文件保存／刪除方式：________________",
                "□ 備份位置和恢復負責人：________________",
            ]
        ),
        heading("4. 不在目前 Demo 範圍內", 2),
        compact_bullets(
            [
                "真實姓名資料庫、自動訊息發送、自動 Drive 上傳及對外分享。",
                "以 AI 解讀自由文字或讓 AI 參與排班決定。",
                "未經貴機構批准的雲端部署、跨境傳輸或第三方分析。",
            ]
        ),
        heading("5. 事故及疑問處理", 2),
        para(
            "如發現上載了不必要的個人資料、錯誤對象取得文件、正式版被篡改或系統狀態與文件不一致，應立即停止使用和分發，保存 run ID／版本／時間作調查，並通知貴機構指定資料負責人及項目團隊。",
            "body_compact",
        ),
        Spacer(1, 4 * mm),
        make_table(
            [
                ["貴機構資料負責人", "職位／內部代號", "確認日期", "項目團隊接收人"],
                ["", "", "", ""],
            ],
            [47 * mm, 44 * mm, 35 * mm, 47 * mm],
            font_size=8.2,
        ),
    ]
    doc_for(path, "私隱與資料處理說明").build(flatten_flowables(story))


def generate_all(output_dir: Path = OUTPUT_DIR) -> list[Path]:
    register_song_fonts()
    global STYLES
    STYLES = build_styles()
    output_dir.mkdir(parents=True, exist_ok=True)
    outputs = [
        output_dir / "01_排班資料移交指南.pdf",
        output_dir / "03_RosterCopiilot_Demo使用手冊.pdf",
        output_dir / "04_私隱與資料處理說明.pdf",
        output_dir / "05_兩週平行試運行與簽署表.pdf",
    ]
    builders = [
        build_confirmation_checklist,
        build_demo_manual,
        build_privacy_note,
        build_parallel_signoff,
    ]
    for builder, output in zip(builders, outputs, strict=True):
        builder(output)
    return outputs


if __name__ == "__main__":
    for generated in generate_all():
        print(generated)
