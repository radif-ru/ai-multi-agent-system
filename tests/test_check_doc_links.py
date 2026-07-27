"""Тесты для scripts/check_doc_links.py."""

from __future__ import annotations

from pathlib import Path

from scripts.check_doc_links import (
    check_section_refs,
    extract_headings,
    extract_links,
    extract_section_refs,
    is_absolute_fs_path,
    is_archived,
    normalize_heading,
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


def test_extract_section_refs_basic():
    text = "См. `_docs/roadmap.md` § «Web-адаптер» и `testing.md` § «Покрытие»."
    refs = extract_section_refs(text)
    assert ("_docs/roadmap.md", "Web-адаптер") in refs
    assert ("testing.md", "Покрытие") in refs


def test_extract_section_refs_skips_code_blocks():
    text = "Real: `a.md` § «Раздел»\n\n```\n`b.md` § «Фейк»\n```\n"
    refs = extract_section_refs(text)
    assert ("a.md", "Раздел") in refs
    assert ("b.md", "Фейк") not in refs


def test_normalize_heading_strips_numbering_and_markup():
    assert normalize_heading("5. Покрытие") == "Покрытие"
    assert normalize_heading("8.2 Правила") == "Правила"
    assert normalize_heading("(N+2). Сводная таблица") == "(N+2). Сводная таблица"
    assert normalize_heading("**Жирный** и `код`") == "Жирный и код"


def test_extract_headings_ignores_code_blocks():
    text = "# Заголовок\n\n```\n# Не заголовок\n```\n\n## 2. Второй\n"
    headings = extract_headings(text)
    assert "Заголовок" in headings
    assert "Второй" in headings
    assert "Не заголовок" not in headings


def _write(root: Path, rel: str, text: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_check_section_refs_ok(tmp_path: Path):
    _write(tmp_path, "_docs/roadmap.md", "# Roadmap\n\n## Web-адаптер\n")
    source = _write(tmp_path, "_docs/mvp.md", "См. `_docs/roadmap.md` § «Web-адаптер».")
    assert check_section_refs(source, tmp_path) == []


def test_check_section_refs_missing_heading(tmp_path: Path):
    _write(tmp_path, "_docs/roadmap.md", "# Roadmap\n\n## Web-адаптер\n")
    source = _write(tmp_path, "_docs/mvp.md", "См. `_docs/roadmap.md` § «Этап 5».")
    errors = check_section_refs(source, tmp_path)
    assert len(errors) == 1
    assert errors[0][2] == "раздел не найден"


def test_check_section_refs_missing_file(tmp_path: Path):
    source = _write(tmp_path, "_docs/mvp.md", "См. `_docs/gone.md` § «Раздел».")
    errors = check_section_refs(source, tmp_path)
    assert len(errors) == 1
    assert errors[0][2] == "файл не найден"


def test_check_section_refs_bare_name_falls_back_to_repo_root(tmp_path: Path):
    _write(tmp_path, "README.md", "# Проект\n\n## Целевая система\n")
    source = _write(tmp_path, "_docs/stack.md", "См. `README.md` § «Целевая система».")
    assert check_section_refs(source, tmp_path) == []


def test_check_section_refs_skips_template_placeholder(tmp_path: Path):
    source = _write(tmp_path, "_board/process.md", "Формат: `<файл>.md` § «<Заголовок>».")
    assert check_section_refs(source, tmp_path) == []


def test_is_archived_closed_sprints(tmp_path: Path):
    archived = _write(tmp_path, "_board/sprints/01-mvp.md", "# Спринт\n")
    live = _write(tmp_path, "_board/process.md", "# Процесс\n")
    assert is_archived(archived, tmp_path)
    assert not is_archived(live, tmp_path)
