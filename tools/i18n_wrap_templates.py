import re
import sys
import argparse
from pathlib import Path

CYR = r"[А-Яа-яЁё]"

# > ...русский... <
TEXT_NODE_RE = re.compile(r">(?!\s*{%)([^<]*" + CYR + r"[^<]*)<")
HAS_DJANGO_TAG_RE = re.compile(r"({{.*?}}|{%.+?%})")
ALREADY_TRANS_RE = re.compile(r"{%\s*(trans|blocktrans)\b")

ATTRS = ["placeholder", "title", "aria-label"]
ATTR_DBL_RE = re.compile(r'(?P<name>' + "|".join(ATTRS) + r')="(?P<val>[^"]*' + CYR + r'[^"]*)"')
ATTR_SGL_RE = re.compile(r"(?P<name>" + "|".join(ATTRS) + r")='(?P<val>[^']*" + CYR + r"[^']*)'")

LOAD_I18N_RE = re.compile(r"{%\s*load\s+[^%]*\bi18n\b", re.IGNORECASE)
EXTENDS_RE = re.compile(r"{%\s*extends\b")

def escape_django_str(s: str, quote='"'):
    """Экранируем только ту кавычку, которую используем внутри {% trans %}."""
    if quote == '"':
        return s.replace('"', '\\"')
    return s.replace("'", "\\'")

def wrap_text_nodes(html: str) -> str:
    def repl(m):
        inner = m.group(1)
        # пропускаем, если уже есть теги Django или перевод
        if HAS_DJANGO_TAG_RE.search(inner) or ALREADY_TRANS_RE.search(inner):
            return m.group(0)
        text = inner.strip()
        if not text:
            return m.group(0)
        # простая обёртка {% trans "..." %}
        return ">{% trans \"" + escape_django_str(text, '"') + "\" %}<"
    return TEXT_NODE_RE.sub(repl, html)

def wrap_attrs(html: str) -> str:
    # двойные кавычки в HTML -> внутри {% trans %} используем одинарные
    def repl_dbl(m):
        name = m.group("name")
        val = m.group("val")
        if ALREADY_TRANS_RE.search(val):
            return m.group(0)
        return '{name}="{{% trans \'{val}\' %}}"'.format(
            name=name,
            val=escape_django_str(val, quote="'"),
        )
    # одинарные кавычки в HTML -> внутри {% trans %} используем двойные
    def repl_sgl(m):
        name = m.group("name")
        val = m.group("val")
        if ALREADY_TRANS_RE.search(val):
            return m.group(0)
        return "{name}='{{% trans \"{val}\" %}}'".format(
            name=name,
            val=escape_django_str(val, quote='"'),
        )

    html = ATTR_DBL_RE.sub(repl_dbl, html)
    html = ATTR_SGL_RE.sub(repl_sgl, html)
    return html

def ensure_load_i18n(html: str) -> str:
    if LOAD_I18N_RE.search(html):
        return html
    lines = html.splitlines()
    insert_at = 0
    for i, line in enumerate(lines[:10]):  # ищем {% extends %} в первых строках
        if EXTENDS_RE.search(line):
            insert_at = i + 1
            break
    lines.insert(insert_at, "{% load i18n %}")
    return "\n".join(lines)

def process_file(path: Path, apply: bool) -> bool:
    original = content = path.read_text(encoding="utf-8", errors="ignore")
    content = ensure_load_i18n(content)
    content = wrap_attrs(content)
    content = wrap_text_nodes(content)

    if content != original:
        if apply:
            bak = path.with_suffix(path.suffix + ".bak")
            if not bak.exists():
                bak.write_text(original, encoding="utf-8")
            path.write_text(content, encoding="utf-8")
        return True
    return False

def main():
    parser = argparse.ArgumentParser(description="Auto-wrap simple Russian texts in Django templates with {% trans %}.")
    parser.add_argument("--apply", action="store_true", help="write changes in place (create .bak backups)")
    parser.add_argument("--root", default=".", help="project root (default: current dir)")
    parser.add_argument("--globs", nargs="*", default=[
        "templates/**/*.html",
        "app_main/templates/**/*.html",
    ], help="glob patterns for templates")
    args = parser.parse_args()

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
