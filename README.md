# Agent Skills

Personal agent skills collection maintained by `backtomyfuture`.

This repository is meant to be consumed through the open agent skills ecosystem.
Use the Skills CLI to install the skills you need; the examples here intentionally
use only `npx skills add`.

Each directory under `skills/` is a standalone skill:

- `notion-to-md` - export Notion pages to Markdown and local media.
- `bark-notify` - send Bark push notifications.
- `publish-zsxq-article` - publish or schedule Markdown/Notion articles to Zsxq.

## Install

Install one skill globally:

```bash
npx skills add backtomyfuture/agent-skills@notion-to-md -g -y
```

Install the current skills:

```bash
npx skills add backtomyfuture/agent-skills@notion-to-md -g -y
npx skills add backtomyfuture/agent-skills@bark-notify -g -y
npx skills add backtomyfuture/agent-skills@publish-zsxq-article -g -y
```

## Layout

```text
agent-skills/
└── skills/
    ├── notion-to-md/
    ├── bark-notify/
    └── publish-zsxq-article/
```

Each skill keeps its own `SKILL.md` plus optional `scripts/`, `references/`,
`assets/`, and `evals/` folders.

## Add A New Skill

1. Create `skills/<skill-name>/`.
2. Add `skills/<skill-name>/SKILL.md` with `name` and `description` frontmatter.
3. Put deterministic helpers in the skill's own `scripts/` folder and longer docs
   in `references/`.
4. Install it with `npx skills add backtomyfuture/agent-skills@<skill-name> -g -y`.
