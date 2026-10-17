from __future__ import annotations

import hashlib

EXEC_SUFFIXES = frozenset(
    {
        ".exe",
        ".dll",
        ".so",
        ".dylib",
        ".bat",
        ".cmd",
        ".ps1",
        ".sh",
        ".com",
        ".scr",
        ".msi",
        ".jar",
        ".apk",
        ".app",
    }
)
EXEC_MAGICS = (
    b"\x7fELF",
    b"MZ",
    b"\xcf\xfa\xed\xfe",
    b"\xce\xfa\xed\xfe",
    b"\xca\xfe\xba\xbe",
    b"#!",
)
MACRO_TOKENS = ("vba", "macros", "oleobject", "activex", "autoopen", "workbook/vba")


def suffix_is_executable(suffix: str) -> bool:
    return suffix.lower() in EXEC_SUFFIXES


def sniff_executable_bytes(raw: bytes) -> bool:
    return any(raw.startswith(m) for m in EXEC_MAGICS)


def member_name_dangerous(name: str) -> bool:
    low = name.lower()
    base = low.split("/")[-1].split("\\")[-1]
    if low.endswith(tuple(EXEC_SUFFIXES)):
        return True
    lowered = low.replace("\\", "/")
    if "vba" in lowered or "macro" in lowered or "activex" in lowered:
        return True
    if base.startswith(".") and base not in (".", ".."):
        return False
    return False


def member_bytes_dangerous(data: bytes) -> bool:
    if sniff_executable_bytes(data):
        return True
    head = data[: 64 * 1024].lower()
    return any(tok.encode() in head for tok in MACRO_TOKENS)


def fingerprint_material(
    category: str, magic: str, root: str, member_hint: str, suffix: str
) -> str:
    material = f"{category}|{magic}|{root}|{member_hint}|{suffix.lower()}".encode()
    return hashlib.sha256(material).hexdigest()[:32]
