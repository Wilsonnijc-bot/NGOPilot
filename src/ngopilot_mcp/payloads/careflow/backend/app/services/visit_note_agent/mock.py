"""Mock LLM/STT fallback for visit_note_agent (full offline demo).

When `settings.dashscope_api_key` is empty, this module supplies
deterministic offline replacements for the LLM contract analyser and
slot-content generator. Combined with the transcriber's mock transcript
fallback, the entire Home-Visit pipeline (phase-1 extraction →
phase-2 rendering) runs end-to-end without any network call — ideal for
hackathon demos and CI.

Contract output adheres to the schema consumed by
`docx_template_renderer.render_docx_from_template`:

    {
        "fixed_blocks":   [{block_id, text}, ...],
        "dynamic_slots":  [{slot_id, source_block_id, label, kind,
                            prefix?, section_hint?}, ...],
        "rules":          [...],
    }

The renderer matches `source_block_id` against the structural
extractor's `block_id` (e.g. `p_001`, `tbl_001_r001_c001`) — keys
produced here are therefore the *actual* block ids, not fabricated ones.
"""
from __future__ import annotations

import re
from typing import Any

_SECTION_RE = re.compile(r"^[一二三四五六七八九十百零〇]+[、.]")
_LABEL_RE = re.compile(r"^([^：:︰]{1,14})[：:︰](.*)$")

# label keyword → mocked value (Hong Kong Cantonese / 繁中)
_MOCK_FIELD_VALUES: list[tuple[str, str]] = [
    ("長者姓名", "陳麗珍婆婆（化名）"),
    ("姓名", "陳麗珍婆婆（化名）"),
    ("性別", "女"),
    ("年齡", "82 歲"),
    ("居住地區", "深水埗區公屋（獨居單位）"),
    ("居住", "深水埗區公屋（獨居單位）"),
    ("同住情況", "獨居"),
    ("同住", "獨居"),
    ("主要照顧者", "兒子陳先生，每星期六探訪一次"),
    ("照顧者", "兒子陳先生，每星期六探訪一次"),
    ("聯絡電話", "9876 5432"),
    ("聯絡", "9876 5432"),
    ("面談日期", "2026 年 5 月 14 日"),
    ("面談地點", "長者家中"),
    ("負責職員", "張姑娘"),
    ("面談方式", "家訪"),
    ("個案類型", "跟進個案"),
    ("負責職員簽署", "張姑娘"),
    ("簽署", "張姑娘"),
    ("日期", "2026 年 5 月 14 日"),
]

# section keyword → mocked paragraph
_MOCK_SECTION_PARAGRAPHS: list[tuple[str, str]] = [
    (
        "近況摘要",
        "陳婆婆表示近日精神尚可，惟膝關節退化令行樓梯吃力，每週外出減至兩、三次。"
        "日常飲食簡單，靠樓下鄰居代購蔬菜；夜眠約四小時，偶有失眠。"
        "情緒方面對節日及夜晚較感孤單，希望多參與中心活動。",
    ),
    (
        "身體健康",
        "長者患膝關節退化及輕度高血壓，定期於普通科門診覆診並按時服藥。"
        "近日反映下蹲及上落樓梯有困難，建議轉介物理治療師上門評估及制定家居運動計劃。",
    ),
    (
        "情緒",
        "整體情緒穩定，但晚上及節日偶感孤單；對中心義工探訪反應正面，願意嘗試長者社交小組。"
        "未見明顯抑鬱徵狀，惟需持續觀察睡眠及胃口變化。",
    ),
    (
        "家居安全",
        "家中浴室目前未設扶手，地面易濕滑，長者曾差點滑倒。廚房夜間光線不足。"
        "建議轉介家居安全評估，跟進浴室扶手、防滑墊及夜燈安裝。",
    ),
    (
        "社交支援",
        "兒子每星期六探望，平日支援有限；樓下鄰居協助買餸。未有恆常參與中心活動，"
        "但對茶聚、健康講座表示興趣，可由職員陪同首次出席以建立信心。",
    ),
    (
        "已提供協助",
        "職員已介紹中心健康講座、長者茶聚及義工恆常探訪服務，"
        "並派發防滑墊樣本、跌倒應變單張及長者卡優惠資料；"
        "同時即場示範起床三步驟以減低低血壓暈眩風險。",
    ),
    (
        "跟進計劃",
        "1) 兩週內安排物理治療師上門評估膝痛；"
        "2) 轉介家居安全評估，重點處理浴室扶手及防滑墊；"
        "3) 邀請陳婆婆參加下週三長者社交小組；"
        "4) 兩週後電話跟進精神、睡眠及社交參與狀況。",
    ),
    (
        "職員觀察",
        "陳婆婆表達清晰，能準確描述自身身體狀況及生活需要。"
        "面談期間態度合作，主動詢問跟進安排，反映其對自身狀況具一定洞察力，"
        "亦具改善意願，是跟進工作有利條件。",
    ),
    (
        "備註",
        "長者同意中心職員作後續電話跟進，並同意初步轉介家居安全評估服務。"
        "所有錄音稿經 Fernet 加密後僅限本機構覆核使用。",
    ),
]

_DOCUMENT_TITLE_HINTS = ("長者個案", "面談紀錄", "家訪紀錄", "家訪報告")


def _is_section_heading(text: str) -> bool:
    if _SECTION_RE.match(text):
        return True
    if any(h in text for h in _DOCUMENT_TITLE_HINTS) and len(text) <= 16:
        return True
    return False


def _match_field_value(label: str) -> str | None:
    for key, value in _MOCK_FIELD_VALUES:
        if key and key in label:
            return value
    return None


def _match_section_paragraph(section_hint: str) -> str | None:
    if not section_hint:
        return None
    for key, value in _MOCK_SECTION_PARAGRAPHS:
        if key in section_hint:
            return value
    return None


def mock_template_contract(structural_map: dict) -> dict:
    """Produce a contract pairing every replaceable block with a slot."""
    blocks = structural_map.get("blocks") or []
    fixed: list[dict] = []
    slots: list[dict] = []
    current_section = ""

    for block in blocks:
        text = (block.get("text") or "").strip()
        if not text:
            continue
        bid = block.get("block_id")
        if not bid:
            continue
        btype = block.get("type") or "paragraph"

        # Section headings stay verbatim & update running section context.
        if btype == "paragraph" and _is_section_heading(text):
            fixed.append({"block_id": bid, "text": text})
            current_section = text
            continue

        # Table cell — treat as a generic dynamic slot.
        if btype == "table_cell":
            slots.append(
                {
                    "slot_id": f"slot_{bid}",
                    "source_block_id": bid,
                    "label": block.get("left_neighbor")
                    or block.get("top_neighbor")
                    or text[:14],
                    "kind": "table_cell",
                    "prefix": "",
                    "section_hint": current_section,
                    "original_text": text,
                }
            )
            continue

        # "label：value" paragraph — generate "label：mocked-value".
        m = _LABEL_RE.match(text)
        if m:
            label = m.group(1).strip()
            slots.append(
                {
                    "slot_id": f"slot_{bid}",
                    "source_block_id": bid,
                    "label": label,
                    "kind": "paragraph",
                    "prefix": f"{label}：",
                    "section_hint": current_section,
                    "original_text": m.group(2).strip(),
                }
            )
            continue

        # Free-form paragraph — slot keyed by its nearest section heading.
        slots.append(
            {
                "slot_id": f"slot_{bid}",
                "source_block_id": bid,
                "label": text[:14],
                "kind": "paragraph",
                "prefix": "",
                "section_hint": current_section,
                "original_text": text,
            }
        )

    if not slots:
        slots.append(
            {
                "slot_id": "summary",
                "source_block_id": None,
                "label": "個案總結",
                "kind": "paragraph",
                "prefix": "",
                "section_hint": "",
                "original_text": "",
            }
        )

    return {
        "fixed_blocks": fixed,
        "dynamic_slots": slots,
        "rules": [
            "Preserve all fixed_blocks verbatim.",
            "Fill dynamic_slots with concise Hong Kong Cantonese / 繁體中文.",
            "Use 「未有明確提及」 when transcript lacks information.",
            "Every value must be reviewable by a human social worker.",
        ],
    }


def mock_slot_content(transcript: str, contract: dict) -> dict[str, Any]:
    """Generate deterministic per-slot content from transcript + contract."""
    transcript_clean = (transcript or "").strip()
    snippet = transcript_clean.replace("\n", " ")[:90] or "（mock 模式 · 暫無語音內容）"
    out: dict[str, Any] = {}

    for slot in contract.get("dynamic_slots", []):
        sid = slot.get("slot_id")
        if not sid:
            continue
        label = slot.get("label") or ""
        prefix = slot.get("prefix") or ""
        section_hint = slot.get("section_hint") or ""

        # 1. "label：value" rows.
        if prefix:
            value = _match_field_value(label) or _match_field_value(
                prefix.rstrip("：:︰")
            )
            if value:
                out[sid] = f"{prefix}{value}"
                continue
            out[sid] = f"{prefix}（AI 草稿 · 待社工核實）"
            continue

        # 2. free-form paragraph under a section heading.
        section_paragraph = _match_section_paragraph(section_hint)
        if section_paragraph:
            out[sid] = section_paragraph
            continue

        # 3. fallback — clearly-marked transcript echo.
        out[sid] = f"【AI 草稿 · {label}】{snippet} …（請社工複核）"

    return out
