#!/usr/bin/env python
import sys
import ast
import re
from pathlib import Path

CYR = re.compile(r"[А-Яа-яЁё]")

GETTEXT_FUNCS = {
    "_", "gettext", "gettext_lazy", "ngettext", "pgettext", "npgettext",
}

def is_docstring_node(node, parent) -> bool:
    # первый Expr(Str) в модуле/классе/функции — это докстринг
    if isinstance(parent, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
        body = parent.body
        if body and body[0] is node:
            return isinstance(node.value, (ast.Str, ast.Constant)) and isinstance(getattr(node.value, "s", None) or getattr(node.value, "value", None), str)
    return False

class I18NChecker(ast.NodeVisitor):
    def __init__(self, filename: str):
        self.filename = filename
        self.issues = []
        self.stack = []  # track parents

    def visit(self, node):
        self.stack.append(node)
        super().visit(node)
        self.stack.pop()

    def in_gettext_context(self) -> bool:
        # true, если где-то выше есть Call к gettext-функции
        for node in reversed(self.stack):
            if isinstance(node, ast.Call):
                fn = node.func
                name = None
                if isinstance(fn, ast.Name):
                    name = fn.id
                elif isinstance(fn, ast.Attribute):
                    name = fn.attr
                if name in GETTEXT_FUNCS:
                    return True
        return False

    def current_parent(self):
        return self.stack[-2] if len(self.stack) >= 2 else None

    def report_if_cyrillic(self, node, s: str):
        if not isinstance(s, str):
            return
        if not CYR.search(s):
            return
        if self.in_gettext_context():
            return
        parent = self.current_parent()
        # Игнорируем докстринги (модуль/класс/функция)
        if isinstance(parent, ast.Expr) and is_docstring_node(parent, self.stack[-3] if len(self.stack) >= 3 else None):
            return
        # Разрешаем локально отключить проверку через комментарий
        if hasattr(node, "lineno"):
            try:
                # прочитать строку и поискать маркер
                line = Path(self.filename).read_text(encoding="utf-8", errors="ignore").splitlines()[node.lineno-1]
                if "# i18n: ignore" in line:
                    return
            except Exception:
                pass
        self.issues.append((node.lineno, getattr(node, "col_offset", 0), s[:80]))

    def visit_Constant(self, node: ast.Constant):
        # Py3.8+: строковые литералы — это Constant
        if isinstance(node.value, str):
            self._check_string(node.value, node)
        self.generic_visit(node)


    def visit_JoinedStr(self, node: ast.JoinedStr):  # f-strings
        # соберём только константные части
        text = "".join([part.value for part in node.values if isinstance(part, ast.Constant) and isinstance(part.value, str)])
        if text:
            self.report_if_cyrillic(node, text)
        self.generic_visit(node)

def check_file(path: Path):
    try:
        src = path.read_text(encoding="utf-8", errors="ignore")
        tree = ast.parse(src, filename=str(path))
    except SyntaxError:
        return []  # не валим коммит, пусть линтеры разбираются

    checker = I18NChecker(str(path))
    checker.visit(tree)
    return checker.issues

def main():
    any_failed = False
    for fname in sys.argv[1:]:
        p = Path(fname)
        if not p.is_file():
            continue
        if p.match("*/migrations/*.py"):
            continue
        issues = check_file(p)
        if issues:
            any_failed = True
            for ln, col, snippet in issues:
                print(f"[i18n-python] {fname}:{ln}:{col}: raw Cyrillic string not wrapped in gettext: {snippet}")
    if any_failed:
        print("\nHint: wrap user-visible Russian strings with _(...), gettext(...), ngettext(...), etc.")
        print("Add '# i18n: ignore' to the line to suppress (e.g. logs/tests).")
        sys.exit(1)

if __name__ == "__main__":
    main()
