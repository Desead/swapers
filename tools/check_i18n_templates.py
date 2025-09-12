#!/usr/bin/env python
import sys
import re
from pathlib import Path

CYR = re.compile(r"[А-Яа-яЁё]")
HAS_DJANGO_TRANS = re.compile(r"{%\s*(trans|blocktrans)\b")
HAS_DJANGO_TAG = re.compile(r"({{.*?}}|{%.+?%})")

STYLE_BLOCK = re.compile(r"<style\b.*?>.*?</style>", re.IGNORECASE | re.DOTALL)
SCRIPT_BLOCK = re.compile(r"<script\b.*?>.*?</script>", re.IGNORECASE | re.DOTALL)
IGNORE_BLOCK = re.compile(r"<!--\s*i18n:\s*ignore\s*start\s*-->.*?<!--\s*i18n:\s*ignore\s*end\s*-->", re.DOTALL | re.IGNORECASE)

ATTR_NEED_TRANS = re.compile(r'\b(placeholder|title|aria-label)\s*=\s*("|\')(.*?)(\2)', re.IGNORECASE)

def should_skip_line(line: str) -> bool:
    s = line.strip()
    if not s:
        return True
    if s.startswith("<!--") or s.startswith("{#"):
        return True
    return False

def check_file(path: Path) -> list[tuple[int, str]]:
    txt = path.read_text(encoding="utf-8", errors="ignore")

    # вырезаем блоки, где кириллица допустима
    txt = IGNORE_BLOCK.sub("", txt)
    txt = STYLE_BLOCK.sub("", txt)
    txt = SCRIPT_BLOCK.sub("", txt)

    problems = []

    for lineno, raw in enumerate(txt.splitlines(), 1):
        line = raw.rstrip("\n")
        if should_skip_line(line):
            continue

        # если строки перевода уже есть
        if HAS_DJANGO_TRANS.search(line):
            continue

        if CYR.search(line):
            # Если это атрибут и в нём нет {% trans %} — флаг
            m = ATTR_NEED_TRANS.search(line)
            if m:
                attr_val = m.group(3)
                if CYR.search(attr_val) and "{% trans" not in attr_val:
                    problems.append((lineno, "Attribute needs {% trans %}: " + m.group(0)))
                    continue

            # Пропускаем служебные Django-теги (вдруг кириллица в комментарии/переменной)
            if HAS_DJANGO_TAG.search(line):
                # всё равно флагнем, если видим «голый» текст вне тегов
                # Heuristic: есть кириллица и нет {% %} в строке => вероятно голый текст
                if "{%" not in line:
                    problems.append((lineno, "Raw Cyrillic text without {% trans %}"))
                continue

            # «голый» текст — точно флаг
            problems.append((lineno, "Raw Cyrillic text without {% trans %}"))

    return problems

def main():
    any_failed = False
    for name in sys.argv[1:]:
        p = Path(name)
        if not p.is_file():
            continue
        issues = check_file(p)
        if issues:
            any_failed = True
            rel = str(p)
            for ln, msg in issues:
                print(f"[i18n-templates] {rel}:{ln}: {msg}")
    if any_failed:
        print("\nHint: wrap user-visible Russian text with {% trans %} or {% blocktrans %}.")
        print("To ignore a block, wrap it with <!-- i18n: ignore start --> ... <!-- i18n: ignore end -->")
        sys.exit(1)

if __name__ == "__main__":
    main()
