#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SKILLS_DIR="$ROOT/skills"
TARGET_DIR="${AGENT_SKILLS_DIR:-$HOME/.agents/skills}"

mkdir -p "$TARGET_DIR"

if [ "$#" -eq 0 ]; then
  skills=()
  while IFS= read -r skill; do
    skills+=("$skill")
  done < <(find "$SKILLS_DIR" -mindepth 1 -maxdepth 1 -type d -exec basename {} \; | sort)
else
  skills=("$@")
fi

for skill in "${skills[@]}"; do
  source_dir="$SKILLS_DIR/$skill"
  target="$TARGET_DIR/$skill"

  if [ ! -f "$source_dir/SKILL.md" ]; then
    echo "missing skill: $skill" >&2
    exit 1
  fi

  if [ -L "$target" ]; then
    rm "$target"
  elif [ -e "$target" ]; then
    backup="$target.backup.$(date +%Y%m%d%H%M%S)"
    mv "$target" "$backup"
    echo "backed up $target to $backup"
  fi

  ln -s "$source_dir" "$target"
  echo "installed $skill -> $target"
done
