#!/usr/bin/env python
import sys
import re
from pathlib import Path

CYR = re.compile(r"[А-Яа-яЁё]")

def main():
    failed = False
    for name in sys.argv[1:]:
        p = Path(name)
        # проверяем и имя файла, и все сегменты пути
        path_str = p.as_posix()
        if CYR.search(path_str):
            print(f"[tpl-cyrillic-name] {path_str}: Cyrillic characters are not allowed in template paths.")
            failed = True
    if failed:
        print("\nHint: rename files/dirs to ASCII-only (e.g. `templates/account/settings.html`).")
        sys.exit(1)

if __name__ == "__main__":
    main()
