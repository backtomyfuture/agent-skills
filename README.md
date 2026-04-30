# Agent Skills

Personal source repository for agent skills maintained by `backtomyfuture`.

Each directory under `skills/` is a standalone skill:

- `notion-to-md` - export Notion pages to Markdown and local media.
- `bark-notify` - send Bark push notifications.
- `publish-zsxq-article` - publish or schedule Markdown/Notion articles to Zsxq.

## Layout

```text
agent-skills/
├── skills/
│   ├── notion-to-md/
│   ├── bark-notify/
│   └── publish-zsxq-article/
└── scripts/
```

Each skill keeps its own `SKILL.md` plus optional `scripts/`, `references/`,
`assets/`, and `evals/` folders.

## Add A New Skill

1. Create `skills/<skill-name>/`.
2. Add `skills/<skill-name>/SKILL.md` with `name` and `description` frontmatter.
3. Put deterministic helpers in `scripts/` and longer docs in `references/`.
4. Run `python3 scripts/check_skills.py`.

## Install Locally

Install or refresh all skills into `~/.agents/skills`:

```bash
scripts/install_local.sh
```

Install one skill:

```bash
scripts/install_local.sh notion-to-md
```

The installer creates symlinks from this repository into `~/.agents/skills`.
If an existing installed skill is a normal directory, it is moved to a timestamped
backup before the symlink is created.

## Validate

```bash
python3 scripts/check_skills.py
```
