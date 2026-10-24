#!/usr/bin/env python3
"""Print a Markdown index of every CURALINK_CONFIG and TODO(CURALINK-MANUAL) marker.

Usage: python3 scripts/config_index.py   (paste output into docs/DEVELOPER_CONFIGURATION.md)
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCAN = [ROOT / "backend" / "app", ROOT / "frontend" / "src", ROOT / ".env.example", ROOT / "run_demo.sh"]
CONFIG = re.compile(r"CURALINK_CONFIG: ([A-Z_]+)")
TODO = re.compile(r"TODO\(CURALINK-MANUAL\):?\s*(.*)")


def files():
    for p in SCAN:
        if p.is_file():
            yield p
        elif p.is_dir():
            yield from (f for f in sorted(p.rglob("*")) if f.suffix in {".py", ".ts", ".tsx"} and "__pycache__" not in f.parts)


def scan():
    configs, todos = [], []
    for f in files():
        for n, line in enumerate(f.read_text(errors="ignore").splitlines(), 1):
            rel = f.relative_to(ROOT)
            for m in CONFIG.finditer(line):
                configs.append((m.group(1), f"{rel}:{n}"))
            if m := TODO.search(line):
                todos.append((f"{rel}:{n}", m.group(1).strip().rstrip('"').strip() or "(see surrounding comment)"))
    return configs, todos


if __name__ == "__main__":
    configs, todos = scan()
    print("| Marker | Location |\n|---|---|")
    for name, loc in sorted(configs):
        print(f"| `{name}` | `{loc}` |")
    print("\n| TODO(CURALINK-MANUAL) location | What's needed |\n|---|---|")
    for loc, text in todos:
        print(f"| `{loc}` | {text} |")
