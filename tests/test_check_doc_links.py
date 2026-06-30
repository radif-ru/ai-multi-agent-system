"""Тесты для scripts/check_doc_links.py."""

from __future__ import annotations

from scripts.check_doc_links import (
    extract_links,
    is_absolute_fs_path,
    strip_code_blocks,
)


def test_extract_links_basic():
    text = "See [docs](docs.md) and [code](../app/main.py)."
    links = extract_links(text)
    assert ("docs", "docs.md") in links
    assert ("code", "../app/main.py") in links


def test_extract_links_skips_urls():
    text = "[site](https://example.com) and [anchor](#section)"
    links = extract_links(text)
    assert ("site", "https://example.com") in links
    assert ("anchor", "#section") in links


def test_extract_links_skips_code_blocks():
    text = (
        "Real link: [ok](real.md)\n\n"
        "```\n[fake](fake.md)\n```\n\n"
        "More text\n"
    )
    links = extract_links(text)
    assert ("ok", "real.md") in links
    assert ("fake", "fake.md") not in links


def test_strip_code_blocks_fence():
    text = "before\n```python\nx = 1\n```\nafter\n"
    result = strip_code_blocks(text)
    assert "x = 1" not in result
    assert "before" in result
    assert "after" in result


def test_strip_code_blocks_tilde():
    text = "before\n~~~\ninner\n~~~\nafter\n"
    result = strip_code_blocks(text)
    assert "inner" not in result
    assert "after" in result


def test_is_absolute_fs_path_unix():
    assert is_absolute_fs_path("/home/user/file.txt")
    assert is_absolute_fs_path("/Users/alice/docs.md")


def test_is_absolute_fs_path_windows():
    assert is_absolute_fs_path("C:\\\\Users\\\\alice")


def test_is_absolute_fs_path_relative():
    assert not is_absolute_fs_path("docs/readme.md")
    assert not is_absolute_fs_path("../app/main.py")
    assert not is_absolute_fs_path("./_docs/security.md")
