"""Check local Markdown/HTML links in tracked documentation without network access."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
LINK = re.compile(r'\[[^\]]*\]\(([^\s)]+)(?:\s+"[^"]*")?\)|(?:src|href)="([^"]+)"')


def anchors(text: str) -> set[str]:
    """GitHub heading slugs, including duplicate headings, for this repo's docs."""
    found: set[str] = set()
    for heading in re.findall(r"^#{1,6}\s+(.+)$", text, re.MULTILINE):
        slug = re.sub(r"[^\w\- ]", "", heading.lower()).replace(" ", "-")
        candidate, suffix = slug, 0
        while candidate in found:
            suffix += 1
            candidate = f"{slug}-{suffix}"
        found.add(candidate)
    found.update(re.findall(r'(?:id|name)="([^"]+)"', text))
    return found


def main() -> int:
    tracked = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).decode().split("\0")
    errors, checked = [], 0
    for name in tracked:
        if not name.endswith(".md"):
            continue
        source = ROOT / name
        body = re.sub(r"^```.*?^```[^\n]*", "", source.read_text("utf-8"), flags=re.MULTILINE | re.DOTALL)
        for match in LINK.finditer(body):
            link = next(value for value in match.groups() if value).strip("<>")
            parsed = urlsplit(link)
            if parsed.scheme or parsed.netloc:
                continue
            target = (source.parent / unquote(parsed.path)).resolve() if parsed.path else source
            checked += 1
            if not target.is_relative_to(ROOT) or not target.exists():
                errors.append(f"{name}: missing or external local target: {link}")
            elif parsed.fragment and target.suffix == ".md":
                if unquote(parsed.fragment) not in anchors(target.read_text("utf-8")):
                    errors.append(f"{name}: missing heading: {link}")
    for error in errors:
        print(error)
    print(f"Checked {checked} local documentation links; {len(errors)} errors.")
    return bool(errors)


if __name__ == "__main__":
    raise SystemExit(main())
