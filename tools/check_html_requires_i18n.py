#!/usr/bin/env python
import sys
import re
from pathlib import Path

# Маркер для осознанного игнора проверки в конкретном файле
IGNORE_MARK = "<!-- i18nload: ignore -->"

HTML_TAG_RE = re.compile(r"<html\b", re.IGNORECASE)
# ищем любую форму: {% load i18n %}, {% load static i18n %}, {% load i18n i18n_extras %}, etc.
LOAD_I18N_RE = re.compile(r"{%\s*load\s+[^%}]*\bi18n\b", re.IGNORECASE)

def check_file(path: Path):
    txt = path.read_text(encoding="utf-8", errors="ignore")
    if IGNORE_MARK in txt:
        return None
    if not HTML_TAG_RE.search(txt):
        return None  # не полноценная страница (вероятно include) — пропускаем
    if LOAD_I18N_RE.search(txt):
        return None
    # <html> есть, но {% load i18n %} не найден
    line = 1 + txt[: txt.lower().find("<html")].count("\n")
    return (line, "Missing `{% load i18n %}` on a template that defines <html>")

def main():
    failed = False
    for name in sys.argv[1:]:
        p = Path(name)
        if not p.is_file():
            continue
        issue = check_file(p)
        if issue:
            ln, msg = issue
            print(f"[tpl-require-load-i18n] {p}:{ln}: {msg}")
            failed = True
    if failed:
        print('\nFix: add at the top of the file, e.g.:\n'
              '  {% load static i18n %}\n'
              'Для редких исключений — вставь маркер в файл: <!-- i18nload: ignore -->')
        sys.exit(1)

if __name__ == "__main__":
    main()
