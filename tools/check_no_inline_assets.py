#!/usr/bin/env python
import sys
import re
from pathlib import Path

# Маркеры для локального отключения проверки в файле
IGNORE_BLOCK = re.compile(r"<!--\s*assets:\s*ignore\s*start\s*-->.*?<!--\s*assets:\s*ignore\s*end\s*-->", re.DOTALL|re.IGNORECASE)

STYLE_BLOCK = re.compile(r"<style\b[^>]*>(.*?)</style>", re.IGNORECASE|re.DOTALL)
# Инлайновый <script> — это тег без src=
SCRIPT_BLOCK = re.compile(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", re.IGNORECASE|re.DOTALL)

def check_file(path: Path):
    txt = path.read_text(encoding="utf-8", errors="ignore")
    clean = IGNORE_BLOCK.sub("", txt)

    issues = []
    for m in STYLE_BLOCK.finditer(clean):
        # Игнорируем пустые/комментарии, но ругаем любой содержательный блок
        content = (m.group(1) or "").strip()
        if content:
            ln = txt[:m.start()].count("\n") + 1
            issues.append((ln, "<style>"))
    for m in SCRIPT_BLOCK.finditer(clean):
        content = (m.group(1) or "").strip()
        if content:
            ln = txt[:m.start()].count("\n") + 1
            issues.append((ln, "<script> (inline)"))
    return issues

def main():
    failed = False
    for name in sys.argv[1:]:
        p = Path(name)
        if not p.is_file():
            continue
        issues = check_file(p)
        if issues:
            failed = True
            for ln, kind in issues:
                print(f"[no-inline-assets] {p}:{ln}: inline {kind} is not allowed (use static files).")
    if failed:
        print("\nHint: move CSS/JS to static/ and link via {% load static %} + <link>/<script src>.")
        print("To ignore a region, wrap it with <!-- assets: ignore start --> ... <!-- assets: ignore end -->")
        sys.exit(1)

if __name__ == "__main__":
    main()
