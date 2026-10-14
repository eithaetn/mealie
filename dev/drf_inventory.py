"""Report registered API operations and direct FastAPI imports for the DRF migration.

Run from the repository root with uv run python dev/drf_inventory.py.
This inspects declarations only; it does not initialize or migrate the database.
"""

import argparse
import ast
import json
import re
import sys
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="Write JSON to this file instead of stdout")
    args = parser.parse_args()
    # Configuration diagnostics must not corrupt the JSON stdout stream.
    with redirect_stdout(sys.stderr):
        from mealie.app import app
        from mealie.drf.asgi import application  # noqa: F401 - initialize Django
        from mealie.drf.urls import urlpatterns

        schema = app.openapi()

    def canonical(path: str) -> str:
        return re.sub(r"\{[^}]+\}|<[^>]+>", "{}", path)

    native = {
        (canonical("/" + str(pattern.pattern)), method.upper())
        for pattern in urlpatterns
        for method in pattern.callback.view_class.http_method_names
    }
    operations = [
        {
            "method": method.upper(),
            "path": path,
            "framework": "drf" if (canonical(path), method.upper()) in native else "fastapi",
        }
        for path, methods in schema["paths"].items()
        for method in methods
        if method in {"get", "post", "put", "patch", "delete", "head", "options"}
    ]
    imports = []
    for directory in ["mealie", "tests", "dev"]:
        for source in sorted((ROOT / directory).rglob("*.py")):
            for node in ast.walk(ast.parse(source.read_text(encoding="utf-8-sig"))):
                modules = []
                line = getattr(node, "lineno", 0)
                if isinstance(node, ast.ImportFrom) and node.module:
                    modules = [node.module]
                elif isinstance(node, ast.Import):
                    modules = [alias.name for alias in node.names]
                for module in modules:
                    if module == "fastapi" or module.startswith("fastapi."):
                        imports.append({"file": source.relative_to(ROOT).as_posix(), "line": line, "module": module})
    payload = json.dumps(
        {
            "note": (
                "DRF owns the listed supported operations. "
                "Legacy declarations still provide OpenAPI and fallback routing."
            ),
            "counts": {kind: sum(op["framework"] == kind for op in operations) for kind in ["drf", "fastapi"]},
            "operations": operations,
            "fastapi_imports": imports,
            "runtime_and_build": ["mealie/app.py", "pyproject.toml", "uv.lock", "dev/code-generation"],
            "outside_openapi": [
                "FastAPI startup/shutdown and documentation routes in mealie/app.py",
                "Production SPA/static mounting and three HTML/manifest routes in mealie/routes/spa/__init__.py",
                "FastAPI import smoke checks in .github/workflows/test-backend.yml and locale-sync.yml",
            ],
        },
        indent=2,
    )
    if args.output:
        args.output.write_text(payload + "\n", encoding="utf-8")
    else:
        sys.stdout.write(payload + "\n")


if __name__ == "__main__":
    main()
