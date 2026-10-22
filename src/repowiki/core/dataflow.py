"""Deterministic data-flow view from the Python AST — no LLM involved.

The dependency graph shows which modules import each other and the call graph
shows who calls whom; this view answers the third orientation question: where
does the project's core data come from, and where does it go. For every class
defined in the project it records which functions *create* it (a constructor
call, or a return annotation naming it) and which functions *receive* it (a
parameter annotation naming the class).

Scope is deliberately narrow: explicit annotations and `ClassName(...)` calls
only, resolved within the project through explicit `from x import C` imports.
Duck-typed construction, factory indirection, and anything dynamic is skipped
rather than guessed. The graph is for orientation, not proof.
"""

from __future__ import annotations

import ast

from .callgraph import _collect_defs, _Def, _explicit_imports, _mermaid_id
from .models import ProjectContext

# Same orientation-aid caps as the call graph: a huge project should still
# render a map, not a hairball.
MAX_NODES = 100
MAX_EDGES = 250


def _annotation_names(node: ast.AST | None) -> set[str]:
    """Every bare name mentioned in an annotation expression.

    `Optional[Foo]`, `list[Foo]`, `Foo | None` all mention `Foo`; we take the
    whole set and let the caller intersect it with known project classes.
    """
    if node is None:
        return set()
    return {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}


def build_dataflow_edges(project: ProjectContext) -> dict[str, set[str]]:
    """Return producer -> consumer edges routed through the shared class.

    Keys and values are node ids (`file:qualname` for functions and classes
    alike). An edge `func -> Class` means the function creates the class; an
    edge `Class -> func` means the function receives it.
    """
    py_files = [f for f in project.files if f.language == "python" and (f.content or f.preview)]
    path_set = {f.path for f in project.files}

    trees: dict[str, ast.Module] = {}
    funcs: dict[str, list[_Def]] = {}
    classes: dict[str, list[str]] = {}  # file -> class qualnames
    class_file: dict[str, str] = {}  # bare class name -> file (when unique)
    bare_counts: dict[str, int] = {}
    for f in py_files:
        try:
            tree = ast.parse(f.content or f.preview or "")
        except SyntaxError:
            continue
        trees[f.path] = tree
        funcs[f.path] = _collect_defs(tree, f.path)
        names: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                names.append(node.name)
        classes[f.path] = names
        for name in names:
            bare_counts[name] = bare_counts.get(name, 0) + 1
    for path, names in classes.items():
        for name in names:
            if bare_counts[name] == 1:
                class_file[name] = path

    def resolve_class(name: str, file: str, imports: dict[str, str]) -> str | None:
        if name in classes.get(file, []):
            return f"{file}:{name}"
        target = imports.get(name)
        if target and name in classes.get(target, []):
            return f"{target}:{name}"
        only = class_file.get(name)
        return f"{only}:{name}" if only else None

    edges: dict[str, set[str]] = {}
    for f in py_files:
        tree = trees.get(f.path)
        if tree is None:
            continue
        imports = _explicit_imports(tree, f.path, path_set)
        for d in funcs.get(f.path, []):
            creates: set[str] = set()
            receives: set[str] = set()
            # return annotation
            for name in _annotation_names(d.node.returns):
                hit = resolve_class(name, f.path, imports)
                if hit:
                    creates.add(hit)
            # parameter annotations
            params = [*d.node.args.posonlyargs, *d.node.args.args, *d.node.args.kwonlyargs]
            for arg in params:
                if arg.arg in ("self", "cls"):
                    continue
                for name in _annotation_names(arg.annotation):
                    hit = resolve_class(name, f.path, imports)
                    if hit:
                        receives.add(hit)
            # constructor calls in the body
            for node in ast.walk(d.node):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                    hit = resolve_class(node.func.id, f.path, imports)
                    if hit:
                        creates.add(hit)
            for cls in creates - receives:
                edges.setdefault(d.node_id, set()).add(cls)
            for cls in receives - creates:
                edges.setdefault(cls, set()).add(d.node_id)
            # a function that both creates and receives the same class is the
            # common "transform" shape; neither edge adds orientation value

    # cap by degree so the render stays a map, not a hairball
    degree: dict[str, int] = {}
    for src, dsts in edges.items():
        degree[src] = degree.get(src, 0) + len(dsts)
        for dst in dsts:
            degree[dst] = degree.get(dst, 0) + 1
    keep = {n for n, _ in sorted(degree.items(), key=lambda kv: -kv[1])[:MAX_NODES]}
    pruned: dict[str, set[str]] = {}
    budget = MAX_EDGES
    for src in sorted(edges, key=lambda s: -degree.get(s, 0)):
        if src not in keep:
            continue
        dsts = [d for d in sorted(edges[src]) if d in keep]
        pruned[src] = set(dsts[: max(budget, 0)])
        budget -= len(pruned[src])
        if budget <= 0:
            break
    return {s: ds for s, ds in pruned.items() if ds}


def to_mermaid(edges: dict[str, set[str]]) -> str:
    """Render the data-flow edges as a Mermaid left-to-right flowchart.

    Function nodes are rectangles, class nodes are stadium-shaped, matching
    the "data in the middle" reading: creator -> Class -> consumer.
    """
    if not edges:
        return ""
    lines = ["graph LR"]
    seen: set[str] = set()
    for src in sorted(edges):
        for dst in sorted(edges[src]):
            for nid in (src, dst):
                if nid in seen:
                    continue
                seen.add(nid)
                short = nid.split(":", 1)[1] if ":" in nid else nid
                if _is_class_node(nid):
                    lines.append(f'    {_mermaid_id(nid)}(["{short}"])')
                else:
                    lines.append(f'    {_mermaid_id(nid)}["{short}"]')
            lines.append(f"    {_mermaid_id(src)} --> {_mermaid_id(dst)}")
    return "\n".join(lines) + "\n"


def _is_class_node(node_id: str) -> bool:
    """Class nodes keep the bare class name as their qualname; function nodes
    end in a lowercase final segment (`main`, `Engine.run`). Check the last
    dotted segment so a method's class prefix is not mistaken for a class."""
    tail = node_id.rsplit(":", 1)[-1].rsplit(".", 1)[-1]
    return tail[:1].isupper()
