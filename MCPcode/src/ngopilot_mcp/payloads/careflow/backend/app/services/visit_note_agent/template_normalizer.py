from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from .errors import VisitNoteAgentError


PDF_UNSUPPORTED_MESSAGE = (
    "PDF templates are no longer supported. Please provide a .docx or .doc template."
)
DOC_CONVERSION_FAILURE_MESSAGE = (
    "Failed to convert .doc template to .docx. Please provide a .docx template."
)
UNSUPPORTED_TEMPLATE_MESSAGE = (
    "Unsupported template type. Please provide a .docx or .doc template."
)


def normalize_template_to_docx(template_path: str, working_dir: str) -> str:
    source = Path(template_path)
    work_dir = Path(working_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    suffix = source.suffix.lower()

    if suffix == ".docx":
        destination = work_dir / "normalized_template.docx"
        shutil.copyfile(source, destination)
        return str(destination)

    if suffix == ".doc":
        return _convert_doc_to_docx(source, work_dir / "normalized_template.docx")

    if suffix == ".pdf":
        raise VisitNoteAgentError(PDF_UNSUPPORTED_MESSAGE)

    raise VisitNoteAgentError(UNSUPPORTED_TEMPLATE_MESSAGE)


def _convert_doc_to_docx(source: Path, destination: Path) -> str:
    if not shutil.which("textutil"):
        raise VisitNoteAgentError(DOC_CONVERSION_FAILURE_MESSAGE)
    try:
        subprocess.run(
            [
                "textutil",
                "-convert",
                "docx",
                "-output",
                str(destination),
                str(source),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        raise VisitNoteAgentError(DOC_CONVERSION_FAILURE_MESSAGE) from exc

    if not destination.exists():
        raise VisitNoteAgentError(DOC_CONVERSION_FAILURE_MESSAGE)
    return str(destination)
