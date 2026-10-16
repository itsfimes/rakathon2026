from __future__ import annotations

import io
import zipfile
from typing import Any
from xml.sax.saxutils import escape

W_MAIN = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"

MARKER = "zxq-marker-7f3a9c"


def para_xml(text: str, style: str | None = None) -> str:
    head = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ""
    return f"<w:p>{head}<w:r><w:t>{escape(text)}</w:t></w:r></w:p>"


def table_xml(rows: list[list[str]]) -> str:
    out: list[str] = []
    for row in rows:
        cells = "".join(f"<w:tc>{para_xml(cell)}</w:tc>" for cell in row)
        out.append(f"<w:tr>{cells}</w:tr>")
    return "<w:tbl>" + "".join(out) + "</w:tbl>"


def body_xml(items: list[tuple[Any, ...]]) -> str:
    parts: list[str] = []
    for item in items:
        if item[0] == "p":
            text = str(item[1])
            style = str(item[2]) if len(item) > 2 else None
            parts.append(para_xml(text, style))
        else:
            rows = item[1]
            assert isinstance(rows, list)
            parts.append(table_xml(rows))
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:document xmlns:w="{W_MAIN}"><w:body>' + "".join(parts) + "</w:body></w:document>"
    )


def make_docx(
    items: list[tuple[Any, ...]],
    *,
    rels_xml: str | None = None,
    extra: list[tuple[str, bytes]] | None = None,
    document_override: bytes | str | None = None,
) -> bytes:
    body: bytes | str = document_override if document_override is not None else body_xml(items)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as handle:
        handle.writestr("[Content_Types].xml", "<Types/>")
        handle.writestr("word/document.xml", body)
        if rels_xml is not None:
            handle.writestr("word/_rels/document.xml.rels", rels_xml)
        for name, data in extra or []:
            handle.writestr(name, data)
    return buf.getvalue()


def rels_xml(mode: str, target: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        f'<Relationship Id="rId9" Type="http://example.org/ref" Target="{target}" TargetMode="{mode}"/>'
        "</Relationships>"
    )
