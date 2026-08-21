from __future__ import annotations

from pathlib import Path

BINARY_EXTENSIONS = frozenset(
    {
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".bmp",
        ".ico",
        ".webp",
        ".pdf",
        ".zip",
        ".gz",
        ".7z",
        ".rar",
        ".exe",
        ".dll",
        ".so",
        ".dylib",
        ".pyc",
        ".pyo",
        ".pyd",
        ".whl",
        ".woff",
        ".woff2",
        ".ttf",
        ".otf",
        ".eot",
        ".mp3",
        ".mp4",
        ".wav",
        ".avi",
        ".mov",
        ".sqlite",
        ".db",
        ".bin",
        ".dat",
        ".class",
        ".o",
        ".obj",
        ".cur",
    }
)

CODE_EXTENSIONS = {
    ".py": "python",
    ".pyw": "python",
    ".js": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".jsx": "javascript",
    ".html": "html",
    ".htm": "html",
    ".css": "css",
    ".scss": "css",
    ".sql": "sql",
    ".sh": "shell",
    ".ps1": "powershell",
    ".bat": "batch",
    ".cmd": "batch",
}

TEXT_EXTENSIONS = {
    ".md": "markdown",
    ".txt": "text",
    ".json": "json",
    ".toml": "toml",
    ".yml": "yaml",
    ".yaml": "yaml",
    ".ini": "ini",
    ".cfg": "ini",
    ".csv": "csv",
    ".xml": "xml",
    ".svg": "xml",
    ".rst": "rst",
    ".log": "text",
}

KIND_CODE = "code"
KIND_TEXT = "text"
KIND_BINARY = "binary"

_SAMPLE = 8192


def classify_file(path: Path, extension: str, sample: bytes | None = None) -> tuple[str, str | None]:
    """Return (kind, language). Binary files are never treated as source."""
    ext = (extension or path.suffix).lower()
    if ext in BINARY_EXTENSIONS:
        return KIND_BINARY, None

    if sample is None:
        sample = _read_sample(path)

    if _looks_binary(sample):
        return KIND_BINARY, None

    if ext in CODE_EXTENSIONS:
        return KIND_CODE, CODE_EXTENSIONS[ext]
    if ext in TEXT_EXTENSIONS:
        return KIND_TEXT, TEXT_EXTENSIONS[ext]
    if not ext:
        return (KIND_TEXT, "text") if not _looks_binary(sample) else (KIND_BINARY, None)
    return KIND_TEXT, "text"


def _read_sample(path: Path) -> bytes:
    try:
        with path.open("rb") as handle:
            return handle.read(_SAMPLE)
    except OSError:
        return b""


def _looks_binary(sample: bytes) -> bool:
    if not sample:
        return False
    if b"\x00" in sample:
        return True
    # High ratio of non-text bytes (excluding common whitespace).
    textish = 0
    for byte in sample:
        if byte in (9, 10, 13) or 32 <= byte <= 126:
            textish += 1
    return (textish / len(sample)) < 0.85


def decode_text(data: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")
