# Agent Skills

Personal agent skills collection maintained by `backtomyfuture`.

This repository is meant to be consumed through the open agent skills ecosystem.
Use the Skills CLI to install the skills you need; the examples here intentionally
use only `npx skills add`.

Each directory under `skills/` is a standalone skill:

- `bark-notify` - send Bark push notifications.
- `exchange-cli` - operate Exchange/Outlook mail, calendar, tasks, and contacts.
- `format-platform-article` - format local Markdown/media into a WeChat-first multi-platform publish package.
- `lark-minutes-base-sync` - sync owned Feishu Minutes into a Base inbox.
- `markdown-table-images` - render publication-risky Markdown tables as PNG images.
- `monthly-attendance` - fill monthly attendance spreadsheets from OA, Notion, and leave records.
- `notion-file-uploader` - upload local files directly to Notion pages.
- `notion-to-email` - convert Notion pages into Outlook-ready HTML/EML email.
- `notion-to-md` - export Notion pages to Markdown and local media.
- `openrouter-paid-ai-index` - build a paid AI inference trend index from OpenRouter rankings and pricing.
- `publish-mdnice-article` - import Markdown/Notion articles into Markdown Nice drafts.
- `publish-xiaohongshu-article` - stage Markdown/Notion articles for Xiaohongshu.
- `publish-zsxq-article` - publish or schedule Markdown/Notion articles to Zsxq.
- `wechat-cli` - query local WeChat chat data with the `wechat-cli` binary.
- `wecom-checkin` - query WeCom attendance/check-in status.
- `youdao-export` - export Youdao Cloud Notes to local files.

## Install

Install one skill globally:

```bash
npx skills add backtomyfuture/agent-skills@notion-to-md -g -y
```

Install the current skills:

```bash
npx skills add backtomyfuture/agent-skills@bark-notify -g -y
npx skills add backtomyfuture/agent-skills@exchange-cli -g -y
npx skills add backtomyfuture/agent-skills@format-platform-article -g -y
npx skills add backtomyfuture/agent-skills@lark-minutes-base-sync -g -y
npx skills add backtomyfuture/agent-skills@markdown-table-images -g -y
npx skills add backtomyfuture/agent-skills@monthly-attendance -g -y
npx skills add backtomyfuture/agent-skills@notion-file-uploader -g -y
npx skills add backtomyfuture/agent-skills@notion-to-email -g -y
npx skills add backtomyfuture/agent-skills@notion-to-md -g -y
npx skills add backtomyfuture/agent-skills@openrouter-paid-ai-index -g -y
npx skills add backtomyfuture/agent-skills@publish-mdnice-article -g -y
npx skills add backtomyfuture/agent-skills@publish-xiaohongshu-article -g -y
npx skills add backtomyfuture/agent-skills@publish-zsxq-article -g -y
npx skills add backtomyfuture/agent-skills@wechat-cli -g -y
npx skills add backtomyfuture/agent-skills@wecom-checkin -g -y
npx skills add backtomyfuture/agent-skills@youdao-export -g -y
```

## Layout

```text
agent-skills/
└── skills/
    ├── bark-notify/
    ├── exchange-cli/
    ├── format-platform-article/
    ├── lark-minutes-base-sync/
    ├── markdown-table-images/
    ├── monthly-attendance/
    ├── notion-file-uploader/
    ├── notion-to-email/
    ├── notion-to-md/
    ├── openrouter-paid-ai-index/
    ├── publish-mdnice-article/
    ├── publish-xiaohongshu-article/
    ├── publish-zsxq-article/
    ├── wechat-cli/
    ├── wecom-checkin/
    └── youdao-export/
```

Each skill keeps its own `SKILL.md` plus optional `scripts/`, `references/`,
`assets/`, and `evals/` folders.

## Add A New Skill

1. Create `skills/<skill-name>/`.
2. Add `skills/<skill-name>/SKILL.md` with `name` and `description` frontmatter.
3. Put deterministic helpers in the skill's own `scripts/` folder and longer docs
   in `references/`.
4. Install it with `npx skills add backtomyfuture/agent-skills@<skill-name> -g -y`.
