"""Проверка относительных ссылок в markdown-документации (спринт 12, задача 8.1).

Скрипт проходит markdown-файлы в `_docs/`, `_board/`, `README.md`, `.agents/`
и проверяет:

1. **Битые ссылки** — относительные пути `[text](relative/path.md)` указывают
   на существующий файл.
2. **Абсолютные пути ФС** — запрещены `_docs/instructions.md` §9
   (`/home/...`, `/Users/...`, `C:\\...`).

Запуск из корня репозитория:

    python -m scripts.check_doc_links

Выход:
- 0 — все ссылки валидны.
- 1 — найдены битые ссылки или абсолютные пути.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

_MARKDOWN_LINK_RE = re.compile(r"\[([^\]]*)\]\(([^)]+)\)")
_ABS_PATH_RE = re.compile(r"(?:/home/|/Users/|[A-Za-z]:\\\\)")
_FENCE_RE = re.compile(r"^(```|~~~)", re.MULTILINE)

_SCAN_DIRS: tuple[str, ...] = ("_docs", "_board", ".agents")
_SCAN_FILES: tuple[str, ...] = ("README.md", "AGENTS.md")


def find_md_files(repo_root: Path) -> list[Path]:
    """Найти все .md файлы в сканируемых каталогах и файлах."""
    result: list[Path] = []
    for dir_name in _SCAN_DIRS:
        directory = repo_root / dir_name
        if directory.is_dir():
            result.extend(directory.rglob("*.md"))
    for file_name in _SCAN_FILES:
        filepath = repo_root / file_name
        if filepath.is_file():
            result.append(filepath)
    return result


def strip_code_blocks(text: str) -> str:
    """Удалить fenced code blocks (``` ... ``` и ~~~ ... ~~~)."""
    lines = text.splitlines(keepends=True)
    result: list[str] = []
    in_fence = False
    for line in lines:
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if not in_fence:
            result.append(line)
    return "".join(result)


def extract_links(text: str) -> list[tuple[str, str]]:
    """Извлечь markdown-ссылки [(label, target), ...] вне code blocks."""
    clean = strip_code_blocks(text)
    return [
        (match.group(1), match.group(2))
        for match in _MARKDOWN_LINK_RE.finditer(clean)
    ]


def is_absolute_fs_path(target: str) -> bool:
    """Проверить, является ли target абсолютным путём ФС."""
    return bool(_ABS_PATH_RE.search(target))


def check_file(
    filepath: Path, repo_root: Path
) -> list[tuple[str, str, str]]:
    """Проверить ссылки в одном файле. Возвращает список (file, target, error)."""
    errors: list[tuple[str, str, str]] = []
    text = filepath.read_text(encoding="utf-8")
    file_rel = filepath.relative_to(repo_root)

    for _label, target in extract_links(text):
        # Пропускаем URL, якоря, mailto
        if target.startswith(("http://", "https://", "#", "mailto:")):
            continue

        # Проверка абсолютных путей ФС
        if is_absolute_fs_path(target):
            errors.append((str(file_rel), target, "абсолютный путь ФС"))
            continue

        # Очищаем якорь в конце пути
        path_part = target.split("#")[0].split(" ")[0]
        if not path_part:
            continue

        # Разрешаем относительно каталога файла
        resolved = (filepath.parent / path_part).resolve()
        if not resolved.exists():
            errors.append((str(file_rel), target, "файл не найден"))

    return errors


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent
    md_files = find_md_files(repo_root)

    all_errors: list[tuple[str, str, str]] = []
    for filepath in md_files:
        all_errors.extend(check_file(filepath, repo_root))

    if all_errors:
        print("ERROR: найдены проблемы со ссылками:\n", file=sys.stderr)
        for file_rel, target, error in all_errors:
            print(f"  {file_rel}: [{target}] — {error}", file=sys.stderr)
        return 1

    print(f"OK: проверено {len(md_files)} файлов, битых ссылок нет")
    return 0


if __name__ == "__main__":
    sys.exit(main())
