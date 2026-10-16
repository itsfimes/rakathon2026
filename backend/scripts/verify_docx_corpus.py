from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from rakathon_backend.b1.docx import DocxError, extract_docx_text

DEFAULT_CORPUS = Path(
    "/mnt/870Ext/sync/programming/rakathon/rakathon2026/vzp_data/rakathon_final_all"
)


def _iter_docs(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*.docx") if p.is_file() and not p.is_symlink())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="verify-docx-corpus")
    parser.add_argument("--corpus", default=str(DEFAULT_CORPUS))
    args = parser.parse_args(argv)
    root = Path(str(args.corpus))
    if not root.is_dir():
        print(json.dumps({"error": "corpus dir is not usable"}))
        return 2
    docs = _iter_docs(root)
    results: list[dict[str, object]] = []
    failed = 0
    for doc in docs:
        try:
            raw = doc.read_bytes()
        except OSError:
            failed += 1
            results.append({"file": doc.name, "ok": False, "reason": "unreadable"})
            continue
        try:
            out = extract_docx_text(raw)
        except DocxError as exc:
            failed += 1
            results.append({"file": doc.name, "ok": False, "reason": exc.code})
            continue
        _ = hashlib.sha256(raw).hexdigest()
        results.append(
            {
                "file": doc.name,
                "ok": True,
                "bytes": len(raw),
                "sha256": out.source_sha256,
                "chars": len(out.text),
                "paragraphs": out.paragraphs,
                "tables": out.tables,
            }
        )
    print(json.dumps({"docs": results, "total": len(docs), "failed": failed}, indent=2))
    return 1 if failed or not docs else 0


if __name__ == "__main__":
    raise SystemExit(main())
