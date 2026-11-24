"""The fence of global singletons: the application keeps no state at import.

    python -m tests.singletons              check app/ and primer_report/
    python -m tests.singletons --selftest   every planted form must be found

The owner's decision of 24.11: the Panel is on the blank's form -- an
application factory, no global singletons. The code it takes from velo and
aivis keeps its engine, sessions, Redis client and settings at module level;
this fence refuses that, in every form of the class, not one spelling:

- ``global`` / ``nonlocal`` -- a function rebinding a name of an outer scope,
  the lazy-singleton pattern (``_engine = None`` ... ``global _engine``);
- a call of a state-holding constructor in a module's or a class's own body
  -- assignment, annotated assignment, a walrus, a bare expression, a tuple,
  inside ``if`` / ``try`` / ``with`` / ``for`` / ``while`` at that level:
  ``DENIED`` by the last name of the called chain, and every class the scanned
  tree derives from ``BaseSettings``;
- ``lru_cache`` / ``cache`` on any function or method -- a hidden instance
  kept for the life of the process.

Calls inside a function, a lambda or a method body are not module state and
are not looked at; nor is ``APIRouter`` at module level, which holds routes,
not state.
"""

import ast
import sys
from collections.abc import Iterator, Sequence
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
AREA = ("app", "primer_report")

DENIED = frozenset(
    {
        "AsyncClient",
        "BaseSettings",
        "ClientSession",
        "ConnectionPool",
        "FastAPI",
        "Redis",
        "Settings",
        "StrictRedis",
        "async_sessionmaker",
        "create_async_engine",
        "create_engine",
        "from_url",
        "sessionmaker",
    }
)
CACHES = frozenset({"lru_cache", "cache"})

_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)


def _name(node: ast.expr) -> str | None:
    """The last name of a called chain: ``a.b.c()`` -> ``c``."""
    if isinstance(node, ast.Call):
        return _name(node.func)
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _settings_classes(trees: Sequence[ast.Module]) -> set[str]:
    """Classes of the scanned tree derived from ``BaseSettings``."""
    out: set[str] = set()
    for tree in trees:
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and any(
                _name(base) == "BaseSettings" for base in node.bases
            ):
                out.add(node.name)
    return out


def _expressions(node: ast.AST) -> Iterator[ast.AST]:
    """Every node under ``node`` that runs where ``node`` runs: not the body
    of a function or a lambda, which runs later, nor a nested class, which is
    a body of its own."""
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (*_SCOPES, ast.ClassDef)):
            continue
        yield child
        yield from _expressions(child)


def _bodies(tree: ast.Module) -> Iterator[list[ast.stmt]]:
    """The module's body and every class body in it, at any depth."""
    yield tree.body
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            yield node.body


def _scope_level(body: list[ast.stmt]) -> Iterator[ast.stmt]:
    """Statements that run in the scope of ``body``: its own and those of the
    blocks it contains (``if``, ``try``, ``with``, ``for``, ``while``,
    ``match``), never a function's or a class's."""
    for statement in body:
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
            # Its decorators and defaults run here; its body does not.
            defaults = [d for d in statement.args.kw_defaults if d is not None]
            for expression in (
                *statement.decorator_list,
                *statement.args.defaults,
                *defaults,
            ):
                yield ast.Expr(value=expression)
            continue
        if isinstance(statement, ast.ClassDef):
            for expression in (*statement.decorator_list, *statement.bases):
                yield ast.Expr(value=expression)
            continue
        yield statement


def findings_of(source: str, path: str, settings: set[str]) -> list[str]:
    """Every singleton form in one module's source."""
    tree = ast.parse(source, filename=path)
    out: list[str] = []
    denied = DENIED | settings
    for node in ast.walk(tree):
        if isinstance(node, (ast.Global, ast.Nonlocal)):
            keyword = "global" if isinstance(node, ast.Global) else "nonlocal"
            out.append(f"{path}:{node.lineno}: {keyword} {', '.join(node.names)}")
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for decorator in node.decorator_list:
                if _name(decorator) in CACHES:
                    out.append(
                        f"{path}:{decorator.lineno}: @{_name(decorator)} on {node.name}"
                    )
    for body in _bodies(tree):
        for statement in _scope_level(body):
            nodes = [statement, *_expressions(statement)]
            for node in nodes:
                if isinstance(node, ast.Call) and _name(node) in denied:
                    out.append(f"{path}:{node.lineno}: {_name(node)}() at import time")
    return out


def findings(root: Path) -> tuple[list[str], int]:
    """Every singleton form under ``root``'s ``AREA``; the number of modules."""
    files = sorted(
        file for part in AREA for file in (root / part).rglob("*.py") if file.is_file()
    )
    sources = {file: file.read_text(encoding="utf-8") for file in files}
    trees = [ast.parse(text, filename=str(file)) for file, text in sources.items()]
    settings = _settings_classes(trees)
    out: list[str] = []
    for file, text in sources.items():
        out += findings_of(text, str(file.relative_to(root)), settings)
    return out, len(files)


# name -> a module with one planted form; each must be found.
PLANTED: dict[str, str] = {
    "global": "_e = None\ndef get():\n    global _e\n    _e = 1\n",
    "nonlocal": "def outer():\n    x = 0\n    def inner():\n        nonlocal x\n",
    "assignment": "engine = create_async_engine('url')\n",
    "annotated": "engine: object = create_async_engine('url')\n",
    "attribute chain": "client = redis.asyncio.Redis.from_url('url')\n",
    "walrus": "(client := Redis())\n",
    "bare call": "FastAPI()\n",
    "tuple": "a, b = 1, sessionmaker()\n",
    "inside if": "if True:\n    pool = ConnectionPool()\n",
    "inside try": "try:\n    s = async_sessionmaker()\nexcept Exception:\n    pass\n",
    "inside with": "with open('x') as f:\n    e = create_engine('url')\n",
    "inside for": "for _ in ():\n    c = AsyncClient()\n",
    "class body": "class Holder:\n    redis = StrictRedis()\n",
    "settings subclass": (
        "class Config(BaseSettings):\n    pass\n\nconfig = Config()\n"
    ),
    "default argument": "def f(e=create_engine('url')):\n    return e\n",
    "decorator call": "@register(FastAPI())\ndef f():\n    pass\n",
    "lru_cache": "@functools.lru_cache\ndef settings():\n    return 1\n",
    "lru_cache called": "@lru_cache(maxsize=1)\ndef settings():\n    return 1\n",
    "cache on a method": "class A:\n    @cache\n    def get(self):\n        return 1\n",
}

# Forms that are not module state; each must pass.
CLEAN: dict[str, str] = {
    "a call in a function": "def make():\n    return create_async_engine('url')\n",
    "a call in a lambda": "make = lambda: Redis()\n",
    "a call in a method": "class A:\n    def make(self):\n        return FastAPI()\n",
    "a router": "router = APIRouter()\n",
}


def selftest() -> list[str]:
    """Names of planted forms not found, and of clean forms found."""
    missed: list[str] = []
    for name, source in PLANTED.items():
        trees = [ast.parse(source)]
        if not findings_of(source, name, _settings_classes(trees)):
            missed.append(f"planted {name!r} was not found")
    for name, source in CLEAN.items():
        found = findings_of(source, name, set())
        if found:
            missed.append(f"clean {name!r} was found: {found[0]}")
    return missed


def main(argv: Sequence[str]) -> int:
    if list(argv) == ["--selftest"]:
        missed = selftest()
        for line in missed:
            print(f"MISSED {line}", file=sys.stderr)
        print(
            f"singletons selftest: {len(PLANTED)} planted, {len(CLEAN)} clean, "
            f"{len(missed)} missed"
        )
        return 1 if missed else 0
    if argv:
        print("usage: python -m tests.singletons [--selftest]", file=sys.stderr)
        return 2
    found, modules = findings(BACKEND)
    for line in found:
        print(line, file=sys.stderr)
    print(f"singletons: {modules} modules, {len(found)} found")
    return 1 if found or not modules else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
