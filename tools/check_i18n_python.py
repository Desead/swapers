#!/usr/bin/env python3
import ast
import pathlib
import re
import sys

CYRILLIC_RE = re.compile(r"[А-Яа-яЁё]")
IGNORE_TOKEN = "i18n: ignore"

DEFAULT_FUNCS = {
    "_",
    "gettext",
    "ngettext",
    "pgettext",
    "npgettext",
    "ugettext",
    "ungettext",
    "gettext_lazy",
}

def _ascii_safe(snippet: str, max_len: int = 60) -> str:
    s = snippet
    if len(s) > max_len:
        s = s[: max_len - 3] + "..."
    # Безопасный вывод в Windows-консоль (cp1251 и пр.)
    return s.encode("ascii", "backslashreplace").decode("ascii")


class I18NChecker(ast.NodeVisitor):
    """
    Ищем «сырую» кириллицу в .py, но:
    - разрешаем, если строка внутри вызова _(…)/gettext(…)/… (с учётом алиасов)
    - игнорируем докстринги (module/class/def)
    - игнорируем отдельные строковые выражения-«комментарии» (Expr(Constant(str)))
    - уважаем подавление строкой '# i18n: ignore'
    """

    def __init__(self, source_text: str, filename: str):
        self.filename = filename
        self.lines = source_text.splitlines()
        self.issues: list[tuple[int, int, str]] = []

        self.allowed_funcs = set(DEFAULT_FUNCS)
        self.allowed_string_nodes: set[int] = set()
        self.docstring_nodes: set[int] = set()
        self.expr_comment_string_nodes: set[int] = set()

        self.suppressed_lines = {
            i for i, line in enumerate(self.lines, start=1) if IGNORE_TOKEN in line
        }

    # ---- сбор алиасов ----
    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        mod = node.module or ""
        if "translation" in mod or mod == "gettext":
            for alias in node.names:
                base = alias.name
                asname = alias.asname or alias.name
                if base in DEFAULT_FUNCS:
                    self.allowed_funcs.add(asname)
        self.generic_visit(node)

    # ---- помечаем строки внутри разрешённых функций ----
    def visit_Call(self, node: ast.Call) -> None:
        func_name = None
        if isinstance(node.func, ast.Name):
            func_name = node.func.id
        elif isinstance(node.func, ast.Attribute):
            func_name = node.func.attr  # module.gettext(...)

        if func_name in self.allowed_funcs:
            def mark_strings(tree: ast.AST) -> None:
                for sub in ast.walk(tree):
                    if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                        self.allowed_string_nodes.add(id(sub))
                    elif isinstance(sub, ast.JoinedStr):  # f-строки
                        for v in sub.values:
                            if isinstance(v, ast.Constant) and isinstance(v.value, str):
                                self.allowed_string_nodes.add(id(v))

            for arg in node.args:
                mark_strings(arg)
            for kw in node.keywords:
                mark_strings(kw.value)

        self.generic_visit(node)

    # ---- помечаем докстринги заранее ----
    def _mark_docstring_in_body(self, body: list[ast.stmt]) -> None:
        if not body:
            return
        first = body[0]
        if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
            self.docstring_nodes.add(id(first.value))

    def visit_Module(self, node: ast.Module) -> None:
        self._mark_docstring_in_body(node.body)
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._mark_docstring_in_body(node.body)
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._mark_docstring_in_body(node.body)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._mark_docstring_in_body(node.body)
        self.generic_visit(node)

    # ---- помечаем строковые «комментарии» (Expr("...")) ----
    def visit_Expr(self, node: ast.Expr) -> None:
        if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            self.expr_comment_string_nodes.add(id(node.value))
        self.generic_visit(node)

    # ---- ищем «сырую» кириллицу ----
    def visit_Constant(self, node: ast.Constant) -> None:
        if not (isinstance(node.value, str) and CYRILLIC_RE.search(node.value)):
            return

        node_id = id(node)
        if (
            node_id in self.allowed_string_nodes
            or node_id in self.docstring_nodes
            or node_id in self.expr_comment_string_nodes
        ):
            return

        lineno = getattr(node, "lineno", 0)
        if lineno in self.suppressed_lines:
            return

        col = getattr(node, "col_offset", 0)
        self.issues.append((lineno, col, node.value))


def check_file(path: str):
    p = pathlib.Path(path)
    try:
        text = p.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        text = p.read_text(encoding="utf-8", errors="ignore")

    tree = ast.parse(text, filename=path)
    checker = I18NChecker(text, path)
    checker.visit(tree)
    return checker.issues


def main():
    paths = [p for p in sys.argv[1:] if p.endswith(".py")]
    bad = False

    for path in paths:
        issues = check_file(path)
        for lineno, col, s in issues:
            print(
                f"[i18n-python] {path}:{lineno}:{col}: "
                f"raw Cyrillic string not wrapped in gettext: {_ascii_safe(s)}"
            )
            bad = True

    if bad:
        print(
            "Hint: wrap user-visible Russian strings with _(...), gettext(...), "
            "ngettext(...), etc. Add '# i18n: ignore' to the line to suppress (e.g. logs/tests)."
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
