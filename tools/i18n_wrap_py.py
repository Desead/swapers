import re
import sys
import argparse
from pathlib import Path

CYR = r"[А-Яа-яЁё]"

# какие именованные аргументы оборачиваем
KWARGS = [
    "label", "help_text", "verbose_name", "verbose_name_plural",
    "empty_label", "title", "description", "placeholder",
]

# kwarg="русский"
def kwarg_regex(name):
    return re.compile(
        rf'(\b{name}\s*=\s*)("|\')([^"\']*{CYR}[^"\']*)\2'
    )

RE_VALIDATION_ERROR = re.compile(
    rf'(raise\s+ValidationError\(\s*)("|\')([^"\']*{CYR}[^"\']*)\2'
)

RE_MESSAGES = re.compile(
    rf'((?:messages\.(?:error|info|success|warning)|messages\.add_message)\s*\(\s*request\s*,\s*(?:[A-Z_]+\s*,\s*)?)("|\')([^"\']*{CYR}[^"\']*)\2'
)

# error_messages={ 'required': '…', ... }
RE_ERR_BLOCK = re.compile(r'(error_messages\s*=\s*\{[^}]*\})', re.DOTALL)
RE_INNER_VAL = re.compile(r'(:\s*)("|\')([^"\']*' + CYR + r'[^"\']*)\2')

RE_HAS_IMPORT = re.compile(r'from\s+django\.utils\.translation\s+import\s+gettext_lazy\s+as\s+_')
RE_IMPORT_LINE = re.compile(r'^(?:import .+|from .+ import .+)$', re.MULTILINE)

def escape_py_string(s: str, quote: str) -> str:
    return s.replace(quote, "\\" + quote)

def should_skip(val: str) -> bool:
    # не лезем в строки, где уже есть перевод или формат-переменные
    low = val.strip()
    if low.startswith("_(") or low.startswith("gettext(") or low.startswith("gettext_lazy("):
        return True
    if "{%" in val or "{{" in val:
        return True
    if "{".encode() in val.encode() or "}".encode() in val.encode():
        return True
    if "%(" in val:  # формат с именованными плейсхолдерами — лучше вручную
        return True
    return False

def wrap_call(val: str, quote: str) -> str:
    return "_(" + quote + escape_py_string(val, quote) + quote + ")"

def process_content(src: str) -> str:
    orig = src

    # 1) простые kwargs: label=, help_text= …
    for name in KWARGS:
        rx = kwarg_regex(name)
        def repl(m):
            prefix, q, val = m.group(1), m.group(2), m.group(3)
            if should_skip(val):
                return m.group(0)
            return f"{prefix}{wrap_call(val, q)}"
        src = rx.sub(repl, src)

    # 2) ValidationError("…")
    def repl_valerr(m):
        prefix, q, val = m.group(1), m.group(2), m.group(3)
        if should_skip(val):
            return m.group(0)
        return f"{prefix}{wrap_call(val, q)}"
    src = RE_VALIDATION_ERROR.sub(repl_valerr, src)

    # 3) messages.*(request, "…")
    def repl_msg(m):
        prefix, q, val = m.group(1), m.group(2), m.group(3)
        if should_skip(val):
            return m.group(0)
        return f"{prefix}{wrap_call(val, q)}"
    src = RE_MESSAGES.sub(repl_msg, src)

    # 4) error_messages={ ... }
    def repl_errblock(m):
        block = m.group(1)
        def inner(m2):
            sep, q, val = m2.group(1), m2.group(2), m2.group(3)
            if should_skip(val):
                return m2.group(0)
            return f"{sep}{wrap_call(val, q)}"
        return RE_INNER_VAL.sub(inner, block)
    src = RE_ERR_BLOCK.sub(repl_errblock, src)

    # 5) импорт gettext_lazy как _
    if src != orig and not RE_HAS_IMPORT.search(src):
        insert_pos = 0
        last = None
        for m in RE_IMPORT_LINE.finditer(src):
            last = m
        line = "from django.utils.translation import gettext_lazy as _\n"
        if last:
            insert_pos = last.end()
            src = src[:insert_pos] + "\n" + line + src[insert_pos:]
        else:
            src = line + src

    return src

def process_file(path: Path, apply: bool) -> bool:
    if path.suffix != ".py":
        return False
    text = path.read_text(encoding="utf-8", errors="ignore")
    new = process_content(text)
    if new != text:
        if apply:
            bak = path.with_suffix(path.suffix + ".bak")
            if not bak.exists():
                bak.write_text(text, encoding="utf-8")
            path.write_text(new, encoding="utf-8")
        return True
    return False

def main():
    ap = argparse.ArgumentParser(description="Wrap simple Russian strings in Python with gettext_lazy _().")
    ap.add_argument("--apply", action="store_true", help="write changes and create .bak backups")
    ap.add_argument("--root", default=".", help="project root")
    ap.add_argument("--globs", nargs="*", default=[
        "app_main/**/*.py",
    ], help="glob patterns")
    args = ap.parse_args()

    root = Path(args.root).resolve()
    changed = []

    for pattern in args.globs:
        for path in root.glob(pattern):
            if path.is_file():
                try:
                    if process_file(path, args.apply):
                        changed.append(path)
                except Exception as e:
                    print(f"[WARN] {path}: {e}", file=sys.stderr)

    if changed:
        print("Changed files:")
        for p in changed:
            try:
                print(" -", p.relative_to(root))
            except Exception:
                print(" -", str(p))
    else:
        print("No changes detected.")

if __name__ == "__main__":
    main()
