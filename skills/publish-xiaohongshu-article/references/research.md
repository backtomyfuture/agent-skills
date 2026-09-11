# Xiaohongshu Publishing Framework Research

Snapshot date: 2026-04-28.

## Findings

- `xpzouying/xiaohongshu-mcp` is a generic backend reference, but it is outside this skill's publishing boundary. Do not use it for publishing.
- `autoclaw-cc/xiaohongshu-skills` is the best fit for an Agent Skill workflow. It uses the user's logged-in bridge session and provides CLI commands for `check-login`, `login`, `fill-publish`, `publish`, `save-draft`, `long-article`, `click-publish`, and related operations. It supports preview/draft flows, which is safer than immediate publishing.
- `aki66938/xhs-toolkit` is a Python MCP toolkit with `smart_publish_note`, `login_xiaohongshu`, task status checks, local/remote images, video, topics, creator data, and cookie management. It requires Chrome/ChromeDriver or remote browser setup, so it is useful but heavier for this user's local skill.
- `ibreez3/xiaohongshu-skill` is a thin skill wrapper around `xiaohongshu-mcp`. It is useful as a reference, but less complete than using `xiaohongshu-mcp` directly or `xiaohongshu-skills` for draft-first publishing.
- Creator-platform UI automation depends on live page structure. Use it only as an explicitly authorized fallback in the existing Ego Lite TaskSpace, after inspecting the page.

## Decision

This local skill should not vendor a full Xiaohongshu automation stack. It should:

1. Prepare clean, deterministic local payload files from Markdown/Notion sources.
2. Prefer `xiaohongshu-skills` because it supports preview/draft and long article mode.
3. Do not use `xiaohongshu-mcp` or `xhs-toolkit`; keep publishing on the local CLI and its bridge.
4. Fall back to Ego Lite TaskSpace UI automation only after live page inspection and an explicit user handoff.

## Useful Links

- https://github.com/xpzouying/xiaohongshu-mcp
- https://github.com/autoclaw-cc/xiaohongshu-skills
- https://github.com/aki66938/xhs-toolkit
- https://github.com/ibreez3/xiaohongshu-skill
- https://creator.xiaohongshu.com/
