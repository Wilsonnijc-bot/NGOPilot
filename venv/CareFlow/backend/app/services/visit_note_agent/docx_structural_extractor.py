from __future__ import annotations

from pathlib import Path
from typing import Any

from docx import Document
from docx.document import Document as DocumentObject
from docx.oxml.table import CT_Tbl
from docx.oxml.text.paragraph import CT_P
from docx.table import Table
from docx.text.paragraph import Paragraph


def extract_docx_structural_map(template_path: str) -> dict[str, Any]:
    document = Document(template_path)
    blocks: list[dict[str, Any]] = []
    paragraph_index = 0
    table_index = 0
    nearest_heading = ""

    for block in _iter_body_blocks(document):
        if isinstance(block, Paragraph):
            text = _clean_text(block.text)
            if not text:
                continue
            paragraph_index += 1
            is_heading = _is_heading(block)
            block_data = _paragraph_block(
                block,
                block_id=f"p_{paragraph_index:03d}",
                text=text,
                paragraph_index=paragraph_index,
                nearest_heading="" if is_heading else nearest_heading,
                container="body",
            )
            blocks.append(block_data)
            if is_heading:
                nearest_heading = text
        else:
            table_index += 1
            blocks.extend(_table_blocks(block, table_index, nearest_heading))

    blocks.extend(_header_footer_blocks(document, "header"))
    blocks.extend(_header_footer_blocks(document, "footer"))

    return {
        "template_path": str(Path(template_path)),
        "format": "docx",
        "block_count": len(blocks),
        "blocks": blocks,
    }


def _iter_body_blocks(document: DocumentObject):
    for child in document.element.body.iterchildren():
        if isinstance(child, CT_P):
            yield Paragraph(child, document)
        elif isinstance(child, CT_Tbl):
            yield Table(child, document)


def _paragraph_block(
    paragraph: Paragraph,
    block_id: str,
    text: str,
    paragraph_index: int,
    nearest_heading: str,
    container: str,
    section_index: int | None = None,
) -> dict[str, Any]:
    is_list_item = _is_list_item(paragraph)
    location: dict[str, Any] = {"paragraph_index": paragraph_index}
    if section_index is not None:
        location["section_index"] = section_index
    return {
        "block_id": block_id,
        "type": "list_item" if is_list_item else "paragraph",
        "text": text,
        "location": location,
        "nearest_heading": nearest_heading,
        "left_neighbor": "",
        "top_neighbor": "",
        "style_name": paragraph.style.name if paragraph.style else "",
        "inside_table": False,
        "is_list_item": is_list_item,
        "container": container,
    }


def _table_blocks(table: Table, table_index: int, nearest_heading: str) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    rows = table.rows
    for row_index, row in enumerate(rows, start=1):
        for column_index, cell in enumerate(row.cells, start=1):
            text = _clean_text(cell.text)
            if not text:
                continue
            left_neighbor = ""
            top_neighbor = ""
            if column_index > 1:
                left_neighbor = _clean_text(row.cells[column_index - 2].text)
            if row_index > 1:
                top_neighbor = _clean_text(rows[row_index - 2].cells[column_index - 1].text)
            blocks.append(
                {
                    "block_id": f"tbl_{table_index:03d}_r{row_index:03d}_c{column_index:03d}",
                    "type": "table_cell",
                    "text": text,
                    "location": {
                        "table_index": table_index,
                        "row": row_index,
                        "column": column_index,
                    },
                    "nearest_heading": nearest_heading,
                    "left_neighbor": left_neighbor,
                    "top_neighbor": top_neighbor,
                    "style_name": "",
                    "inside_table": True,
                    "is_list_item": False,
                    "container": "body",
                }
            )
    return blocks


def _header_footer_blocks(document: DocumentObject, container: str) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for section_index, section in enumerate(document.sections, start=1):
        part = section.header if container == "header" else section.footer
        paragraph_index = 0
        for paragraph in part.paragraphs:
            text = _clean_text(paragraph.text)
            if not text:
                continue
            paragraph_index += 1
            blocks.append(
                _paragraph_block(
                    paragraph,
                    block_id=f"{container}_{section_index:03d}_p{paragraph_index:03d}",
                    text=text,
                    paragraph_index=paragraph_index,
                    nearest_heading="",
                    container=container,
                    section_index=section_index,
                )
            )
    return blocks


def _clean_text(text: str) -> str:
    return " ".join(text.split()).strip()


def _is_heading(paragraph: Paragraph) -> bool:
    style_name = paragraph.style.name if paragraph.style else ""
    return style_name.lower().startswith("heading")


def _is_list_item(paragraph: Paragraph) -> bool:
    style_name = paragraph.style.name.lower() if paragraph.style else ""
    if "list" in style_name or "bullet" in style_name or "number" in style_name:
        return True
    ppr = paragraph._p.pPr
    return bool(ppr is not None and ppr.numPr is not None)
