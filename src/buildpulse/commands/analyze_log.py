"""Extract structured compiler/linker diagnostics from a raw build log."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass

# GCC / Clang: path/to/file.cpp:12:5: error: message
_GCC = re.compile(
    r"^(?P<file>[^\s:][^:]*):(?P<line>\d+):(?:(?P<col>\d+):)?\s*"
    r"(?:fatal )?(?P<severity>error|warning):\s*(?P<message>.*)$"
)
# MSVC: path\to\file.cpp(12,5): error C2065: message
_MSVC = re.compile(
    r"^(?P<file>[^(]+)\((?P<line>\d+)(?:,(?P<col>\d+))?\):\s*"
    r"(?:fatal )?(?P<severity>error|warning)\s+(?P<code>[A-Z]+\d+):\s*(?P<message>.*)$"
)
# GNU ld / lld: undefined reference / undefined symbol
_LINKER = re.compile(r"(?P<message>undefined (?:reference to|symbol:?)\s*.*)$")


@dataclass
class Issue:
    kind: str  # compiler | linker
    severity: str  # error | warning
    message: str
    file: str | None = None
    line: int | None = None
    column: int | None = None
    code: str | None = None


def parse(text: str) -> list[Issue]:
    issues: list[Issue] = []
    seen: set[tuple] = set()
    for raw in text.splitlines():
        line = raw.strip()
        issue = _match_compiler(line) or _match_linker(line)
        if issue is None:
            continue
        key = (issue.file, issue.line, issue.message)
        if key not in seen:
            seen.add(key)
            issues.append(issue)
    return issues


def _match_compiler(line: str) -> Issue | None:
    m = _GCC.match(line) or _MSVC.match(line)
    if not m:
        return None
    g = m.groupdict()
    return Issue(
        kind="compiler",
        severity=g["severity"],
        message=g["message"].strip(),
        file=g["file"].strip(),
        line=int(g["line"]),
        column=int(g["col"]) if g.get("col") else None,
        code=g.get("code"),
    )


def _match_linker(line: str) -> Issue | None:
    m = _LINKER.search(line)
    if not m:
        return None
    return Issue(kind="linker", severity="error", message=m["message"].strip())


def render(issues: list[Issue], as_json: bool = False) -> str:
    if as_json:
        return json.dumps([asdict(i) for i in issues], indent=2)
    if not issues:
        return "no diagnostics found"
    out = []
    for i in issues:
        loc = f"{i.file}:{i.line}" if i.file else "<link>"
        code = f" [{i.code}]" if i.code else ""
        out.append(f"{i.severity:<7} {i.kind:<8} {loc}{code}: {i.message}")
    errors = sum(i.severity == "error" for i in issues)
    out.append(f"{errors} error(s), {len(issues) - errors} warning(s)")
    return "\n".join(out)
