from __future__ import annotations

import csv
import re
from pathlib import Path

from ..contracts import ExtractedSection


def text_sections(text: str, default_title: str, markdown: bool = False) -> list[ExtractedSection]:
    sections: list[ExtractedSection] = []
    heading = default_title
    body: list[str] = []
    for raw_line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = raw_line.rstrip()
        is_heading = markdown and bool(re.match(r"^#{1,6}\s+\S", line))
        if is_heading:
            content = "\n".join(body).strip()
            if content:
                sections.append(ExtractedSection(None, heading, content))
            heading = re.sub(r"^#{1,6}\s+", "", line).strip()
            body = []
        else:
            body.append(line)
    content = "\n".join(body).strip()
    if content:
        sections.append(ExtractedSection(None, heading, content))
    return sections


def extract_text(path: Path, suffix: str, title: str) -> list[ExtractedSection]:
    if suffix in {".txt", ".md"}:
        return text_sections(path.read_text(encoding="utf-8-sig"), title, suffix == ".md")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = ["\t".join(cell.strip() for cell in row) for row in csv.reader(handle)]
    content = "\n".join(row for row in rows if row.strip()).strip()
    return [ExtractedSection(None, title, content)]
