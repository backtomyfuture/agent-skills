# Research Notes

Snapshot date: 2026-05-06.

## Inputs Used

- WeChat article: "我用Hermes通过5个Agent搭了一条内容自动生产线..." described a five-part pipeline: Scout, Writer, Publisher, Feedback, Orchestrator. The useful pattern is not the number of agents, but the separation between information collection, quality gates, browser staging, and feedback.
- `agency-agents-zh/marketing/marketing-daily-news-briefing.md` provides a stronger Scout/News Intelligence contract: multiple source categories, heat/freshness/confidence levels, source reliability, cross-verification, target platform notes, and downstream content angles.

## Public References

- News intelligence reference:
  - https://github.com/jnMetaCode/agency-agents-zh/blob/main/marketing/marketing-daily-news-briefing.md
- Hermes Agent:
  - https://github.com/NousResearch/hermes-agent
  - https://hermes-agent.nousresearch.com/docs/user-guide/features/cron
  - https://hermes-agent.nousresearch.com/docs/user-guide/features/skills/
- Toutiao creator entry points observed in public references:
  - https://mp.toutiao.com/
  - https://mp.toutiao.com/profile_v4/graphic/publish
  - https://mp.toutiao.com/profile_v4/weitoutiao/publish
- Toutiao open API limitation:
  - https://open.douyin.com/platform/resource/docs/ability/content-management/toutiao-publish-solution/
  - The public open-api path supports posting short videos to Toutiao, but the documented limitation says it does not support Toutiao articles or micro-posts. Browser staging is therefore the practical path for article/micro-post publishing.
- AI-generated content labeling compliance:
  - https://www.cac.gov.cn/2025-03/14/c_1743654685899683.htm

## Design Decisions

1. Keep this as a manual skill. No cron or autonomous monitor is created.
2. Use source transparency as the main guardrail. The brief contract exists so downstream writing does not invent facts.
3. Default to staged/autosaved editor state. Final publish requires explicit user confirmation.
4. Keep login out of scope. The user handles login in a headed browser.
5. Bundle only deterministic helpers. The agent still handles web research, writing, review, and live browser adaptation.

## 2026-05-07 Live Run Corrections

- Ego Lite TaskSpace is the browser boundary for staging and explicit final
  publication. Login is handed off to the user and resumed with the same
  `taskSpaceId`; the skill does not access persistent browser credentials.
- Long editor content may not be fully visible in a compact page observation.
  Verify local payload completeness and sample opening, middle, and ending
  phrases instead of trusting only the first rendered paragraphs.
- Toutiao may expose only `预览`, `定时发布`, and `预览并发布`, with no explicit
  `保存草稿` button. Default safe status is `staged_autosaved`.
- Self-media benchmark/ranking claims should be downgraded or removed unless
  independently confirmed.
- The desired workflow is autonomous topic selection from hot/current sources,
  not waiting for the user to choose every angle. Ask only when risk or
  ambiguity materially changes the article.

## 2026-05-07 Tool Research

- ClawHub `axdlee/toutiao-publish` documents a useful Toutiao visual pattern: AI recommended inline images and free stock cover images. The listing was marked suspicious by ClawHub security scans, so this skill should not install or execute it directly.
- `chemany/toutiao_mcp_server` advertises a richer MCP backend for publishing, micro-posts, images, and data, but it includes login/cookie handling inside the server. That boundary conflicts with this local skill's user-managed login approach.
- The official Douyin/Toutiao open API page only covers video publishing and explicitly does not support articles or micro-posts, so browser staging remains necessary for the target content types.
- `opencli 36kr hot` is a plausible discovery source, but this run hit `BROWSER_CONNECT`; the skill now says to fall back to web search and log the connector issue.
