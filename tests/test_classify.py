from pathlib import Path

from aidycai.infrastructure.classify import (
    KIND_BINARY,
    KIND_CODE,
    KIND_TEXT,
    classify_file,
)


def test_detects_python_as_code(tmp_path):
    path = tmp_path / "main.py"
    path.write_text("x = 1\n", encoding="utf-8")
    kind, language = classify_file(path, ".py")
    assert kind == KIND_CODE
    assert language == "python"


def test_detects_markdown_as_text(tmp_path):
    path = tmp_path / "README.md"
    path.write_text("hola\n", encoding="utf-8")
    kind, language = classify_file(path, ".md")
    assert kind == KIND_TEXT
    assert language == "markdown"


def test_detects_png_extension_as_binary(tmp_path):
    path = tmp_path / "logo.png"
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)
    kind, language = classify_file(path, ".png")
    assert kind == KIND_BINARY
    assert language is None


def test_null_bytes_mark_unknown_extension_binary(tmp_path):
    path = tmp_path / "blob.xyz"
    path.write_bytes(b"\x00\x01\x02\x03" * 100)
    kind, language = classify_file(path, ".xyz")
    assert kind == KIND_BINARY
