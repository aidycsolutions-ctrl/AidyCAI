from __future__ import annotations

import ast
import re
from typing import Any

from aidycai.domain.index_models import ExtractedImport, ExtractedSymbol, FileAnalysis


class PythonAstAnalyzer:
    language = "python"

    def analyze(self, rel_path: str, source: str) -> FileAnalysis:
        tree = ast.parse(source, filename=rel_path)
        visitor = _Visitor()
        visitor.visit(tree)
        module_name = rel_path.rsplit("/", 1)[-1]
        if module_name.endswith(".py"):
            module_name = module_name[:-3]
        module = ExtractedSymbol(
            type="module",
            name=module_name,
            qualified_name=module_name,
            line_start=1,
            line_end=getattr(tree, "end_lineno", None),
            metadata={"rel_path": rel_path},
        )
        return FileAnalysis(symbols=(module, *visitor.symbols), imports=tuple(visitor.imports))


class _Visitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.class_stack: list[str] = []
        self.fn_stack: list[str] = []
        self.symbols: list[ExtractedSymbol] = []
        self.imports: list[ExtractedImport] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        qname = ".".join((*self.class_stack, node.name))
        metadata = {
            "bases": [_expr_name(base) for base in node.bases],
            "decorators": [_expr_name(dec) for dec in node.decorator_list],
        }
        self.symbols.append(
            ExtractedSymbol(
                type="class",
                name=node.name,
                qualified_name=qname,
                line_start=node.lineno,
                line_end=getattr(node, "end_lineno", node.lineno),
                metadata=metadata,
            )
        )
        for decorator in node.decorator_list:
            self._decorator_symbol(decorator, node.lineno, qname)
        self.class_stack.append(node.name)
        self.generic_visit(node)
        self.class_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node, is_async=False)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node, is_async=True)

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self.imports.append(
                ExtractedImport(
                    import_type="import",
                    module=alias.name,
                    names=(),
                    alias=alias.asname,
                    line=node.lineno,
                    level=0,
                )
            )

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        names = tuple(alias.name for alias in node.names)
        module = node.module or ""
        self.imports.append(
            ExtractedImport(
                import_type="from",
                module=module,
                names=names,
                alias=None,
                line=node.lineno,
                level=node.level or 0,
            )
        )

    def visit_Assign(self, node: ast.Assign) -> None:
        if self.class_stack or self.fn_stack:
            return
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id.isupper():
                self.symbols.append(
                    ExtractedSymbol(
                        type="constant",
                        name=target.id,
                        qualified_name=target.id,
                        line_start=node.lineno,
                        line_end=getattr(node, "end_lineno", node.lineno),
                        metadata={},
                    )
                )

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if self.class_stack or self.fn_stack:
            return
        target = node.target
        if isinstance(target, ast.Name) and target.id.isupper():
            self.symbols.append(
                ExtractedSymbol(
                    type="constant",
                    name=target.id,
                    qualified_name=target.id,
                    line_start=node.lineno,
                    line_end=getattr(node, "end_lineno", node.lineno),
                    metadata={"annotated": True},
                )
            )

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef, *, is_async: bool) -> None:
        params = [arg.arg for arg in node.args.args]
        if self.fn_stack:
            kind = "function"
            qname = ".".join((*self.class_stack, *self.fn_stack, node.name))
            parent = self.fn_stack[-1]
        elif self.class_stack:
            kind = "method"
            qname = ".".join((*self.class_stack, node.name))
            parent = self.class_stack[-1]
        else:
            kind = "function"
            qname = node.name
            parent = None
        metadata: dict[str, Any] = {
            "params": params,
            "async": is_async,
            "decorators": [_expr_name(dec) for dec in node.decorator_list],
            "calls": _called_names(node),
            "sql_operations": _sql_operations(node),
        }
        if parent is not None:
            metadata["parent"] = parent
            if kind == "method":
                metadata["class"] = parent
        self.symbols.append(
            ExtractedSymbol(
                type=kind,
                name=node.name,
                qualified_name=qname,
                line_start=node.lineno,
                line_end=getattr(node, "end_lineno", node.lineno),
                metadata=metadata,
            )
        )
        for decorator in node.decorator_list:
            self._decorator_symbol(decorator, node.lineno, qname)
        self.fn_stack.append(node.name)
        self.generic_visit(node)
        self.fn_stack.pop()

    def _decorator_symbol(self, decorator: ast.expr, line: int, owner: str) -> None:
        name = _expr_name(decorator)
        if not name:
            return
        self.symbols.append(
            ExtractedSymbol(
                type="decorator",
                name=name,
                qualified_name=f"{owner}@{name}",
                line_start=line,
                line_end=line,
                metadata={"owner": owner},
            )
        )


_SQL_RESOURCE = re.compile(r"\b(?:FROM|INTO|UPDATE|JOIN)\s+([A-Za-z_][\w$]*(?:\.[A-Za-z_][\w$]*)?)", re.IGNORECASE)
_SQL_KIND = re.compile(r"^\s*(SELECT|INSERT|UPDATE|DELETE)\b", re.IGNORECASE)
_SQL_COLUMNS = re.compile(r"^\s*SELECT\s+(.*?)\s+FROM\b", re.IGNORECASE | re.DOTALL)
_SQL_INSERT_COLUMNS = re.compile(r"^\s*INSERT\s+INTO\s+[^ (]+\s*\((.*?)\)", re.IGNORECASE | re.DOTALL)
_SQL_WHERE = re.compile(r"\bWHERE\s+(.*?)(?:\bGROUP\s+BY\b|\bORDER\s+BY\b|\bLIMIT\b|$)", re.IGNORECASE | re.DOTALL)
_COLUMN_NAME = re.compile(r"\b([A-Za-z_][\w$]*)\b")


def _static_string(node: ast.expr) -> str | None:
    try:
        value = ast.literal_eval(node)
    except (ValueError, TypeError, SyntaxError):
        return None
    return value if isinstance(value, str) else None


def _sql_operations(node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[dict[str, Any]]:
    operations: list[dict[str, Any]] = []

    class Visitor(ast.NodeVisitor):
        def visit_FunctionDef(self, child: ast.FunctionDef) -> None:
            if child is not node:
                return
            self.generic_visit(child)

        def visit_AsyncFunctionDef(self, child: ast.AsyncFunctionDef) -> None:
            if child is not node:
                return
            self.generic_visit(child)

        def visit_ClassDef(self, child: ast.ClassDef) -> None:
            return

        def visit_Call(self, child: ast.Call) -> None:
            method = _expr_name(child.func).lower()
            if method.endswith(".execute") or method == "execute":
                sql = _static_string(child.args[0]) if child.args else None
                if sql:
                    kind_match = _SQL_KIND.match(sql)
                    resource_match = _SQL_RESOURCE.search(sql)
                    if kind_match and resource_match:
                        kind = kind_match.group(1).upper()
                        resource = resource_match.group(1)
                        columns: list[str] = []
                        col_match = _SQL_COLUMNS.search(sql) or _SQL_INSERT_COLUMNS.search(sql)
                        if col_match:
                            for token in col_match.group(1).split(","):
                                name_match = _COLUMN_NAME.search(token.strip().split(" AS ")[0])
                                if name_match:
                                    columns.append(name_match.group(1))
                        predicates: list[str] = []
                        where_match = _SQL_WHERE.search(sql)
                        if where_match:
                            predicates = [m.group(1) for m in re.finditer(r"\b([A-Za-z_][\w$]*)\s*(?:=|<|>|<=|>=|LIKE|IN)\b", where_match.group(1), re.IGNORECASE)]
                        operations.append({
                            "kind": kind,
                            "resource": resource,
                            "line": child.lineno,
                            "columns": columns,
                            "predicates": predicates,
                        })
            self.generic_visit(child)

    Visitor().visit(node)
    return operations


def _called_names(node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
    """Return names called directly from a function body.

    Nested functions/classes are skipped so a caller only receives calls that
    belong to its own execution body.
    """
    found: list[str] = []

    class _CallVisitor(ast.NodeVisitor):
        def visit_FunctionDef(self, child: ast.FunctionDef) -> None:
            if child is not node:
                return
            self.generic_visit(child)

        def visit_AsyncFunctionDef(self, child: ast.AsyncFunctionDef) -> None:
            if child is not node:
                return
            self.generic_visit(child)

        def visit_ClassDef(self, child: ast.ClassDef) -> None:
            return

        def visit_Call(self, child: ast.Call) -> None:
            name = _expr_name(child.func)
            if name and name not in found:
                found.append(name)
            self.generic_visit(child)

    visitor = _CallVisitor()
    for statement in node.body:
        visitor.visit(statement)
    return found


def _expr_name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _expr_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    if isinstance(node, ast.Call):
        return _expr_name(node.func)
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return node.__class__.__name__
