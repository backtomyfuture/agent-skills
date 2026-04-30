#!/usr/bin/env python3
"""Validate the lightweight structure of every skill in this repository."""

from __future__ import annotations

import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILLS_DIR = ROOT / "skills"
REQUIRED_KEYS = ("name", "description")


def parse_frontmatter(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise ValueError("missing YAML frontmatter")

    end = text.find("\n---", 4)
    if end == -1:
        raise ValueError("unterminated YAML frontmatter")

    frontmatter = text[4:end]
    values: dict[str, str] = {}
    current_key: str | None = None

    for raw_line in frontmatter.splitlines():
        if not raw_line.strip():
            continue

        match = re.match(r"^([A-Za-z0-9_-]+):\s*(.*)$", raw_line)
        if match:
            current_key = match.group(1)
            values[current_key] = match.group(2).strip()
            continue

        if current_key and raw_line.startswith((" ", "\t")):
            values[current_key] = (values[current_key] + " " + raw_line.strip()).strip()

    return values


def validate_skill(skill_dir: Path) -> list[str]:
    errors: list[str] = []
    skill_file = skill_dir / "SKILL.md"

    if not skill_file.exists():
        return [f"{skill_dir.relative_to(ROOT)}: missing SKILL.md"]

    try:
        frontmatter = parse_frontmatter(skill_file)
    except ValueError as exc:
        return [f"{skill_file.relative_to(ROOT)}: {exc}"]

    for key in REQUIRED_KEYS:
        if not frontmatter.get(key):
            errors.append(f"{skill_file.relative_to(ROOT)}: missing {key!r}")

    name = frontmatter.get("name", "")
    if name and name != skill_dir.name:
        errors.append(
            f"{skill_file.relative_to(ROOT)}: name {name!r} does not match directory {skill_dir.name!r}"
        )

    return errors


def main() -> int:
    if not SKILLS_DIR.exists():
        print("missing skills/ directory", file=sys.stderr)
        return 1

    skill_dirs = sorted(path for path in SKILLS_DIR.iterdir() if path.is_dir())
    if not skill_dirs:
        print("no skills found", file=sys.stderr)
        return 1

    errors: list[str] = []
    for skill_dir in skill_dirs:
        errors.extend(validate_skill(skill_dir))

    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1

    print(f"OK: {len(skill_dirs)} skills validated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
