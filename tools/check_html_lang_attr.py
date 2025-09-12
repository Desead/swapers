#!/usr/bin/env python
import sys
import re
from pathlib import Path

IGNORE_MARK = "<!-- lang: ignore -->"
HTML_TAG_RE = re.compile(r"<html\b", re.IGNORECASE)
# допускаем lang="{{ CUR_LANG }}" ИЛИ lang="{{ request.LANGUAGE_CODE }}"
LANG_OK_RE = re.compile(
    r'lang\s*=\s*([\'"])\s*\{\{\s*(CUR_LANG|request\.LANGUAGE_CODE)\s*\}\}\s*\1',
    re.IGNORECASE,
)

def check_file(path: Path):
    txt = path.read_text(encoding="utf-8", errors="ignore")
    if IGNORE_MARK in txt:
        return None  # пропускаем намеренно
    if not HTML_TAG_RE.search(txt):
        return None  # не скелет страницы; include/partial — игнорим
    if LANG_OK_RE.search(txt):
        return None
    # если есть <html>, но нет нужного lang — ошибка
    line = 1 + txt[: txt.lower().find("<html")].count("\n")
    return (line, "Missing lang=\"{{ CUR_LANG }}\" (or {{ request.LANGUAGE_CODE }}) on <html>")

def main():
    failed = False
    for name in sys.argv[1:]:
        p = Path(name)
        if not p.is_file():
            continue
        issue = check_file(p)
        if issue:
            ln, msg = issue
            print(f"[tpl-html-lang] {p}:{ln}: {msg}")
            failed = True
    if failed:
        print('\nFix example:\n'
              '  {% load i18n %}\n'
              '  {% get_current_language as CUR_LANG %}\n'
              '  <!doctype html>\n'
              '  <html lang="{{ CUR_LANG }}">\n'
              'Если нужно пропустить файл, добавь в него маркер: <!-- lang: ignore -->')
        sys.exit(1)

if __name__ == "__main__":
    main()
