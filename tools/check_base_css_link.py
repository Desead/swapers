#!/usr/bin/env python
import sys
from pathlib import Path

NEEDLE_SINGLE = "{% static 'css/base.css' %}"
NEEDLE_DOUBLE = '{% static "css/base.css" %}'

def main():
    failed = False
    for name in sys.argv[1:]:
        p = Path(name)
        if not p.is_file():
            continue
        txt = p.read_text(encoding="utf-8", errors="ignore")
        if NEEDLE_SINGLE not in txt and NEEDLE_DOUBLE not in txt:
            print(f"[base-css] {p}: <link rel='stylesheet' href=\"{{% static 'css/base.css' %}}\"> not found.")
            failed = True
    if failed:
        print("\nFix: ensure base.html has <link rel=\"stylesheet\" href=\"{% static 'css/base.css' %}\"> in <head>.")
        sys.exit(1)

if __name__ == "__main__":
    main()
