# Toutiao Tools And Format Notes

Snapshot date: 2026-05-07.

## Existing Tools Found

### `axdlee/toutiao-publish` on ClawHub

Reference: https://clawhub.ai/axdlee/toutiao-publish

Useful ideas:

- Supports both articles and micro-posts.
- Uses the Toutiao creator page rather than a public article API.
- Documents dynamic refs and the need to re-snapshot before interaction.
- Uses Toutiao's AI recommended images for inline visuals.
- Uses Toutiao's free stock image library for cover images.

Limitations for this local skill:

- ClawHub marks the skill as suspicious in security scans, so do not install or execute it blindly.
- It is written for a different browser automation interface (`browser act` / `evaluate`), not this environment's `agent-browser` command style.
- It emphasizes final publishing; this local skill defaults to staged/autosaved.

Decision: borrow the image/cover ideas and dynamic-ref caution, but keep our local implementation.

### `chemany/toutiao_mcp_server`

Reference: https://github.com/chemany/toutiao_mcp_server

Useful ideas:

- Advertises content publishing, micro-post publishing, image upload/compression, and data analysis as an MCP server.
- Could be useful if the user later wants a persistent local MCP backend.

Limitations:

- Login and cookie handling are part of the server boundary, while this skill intentionally keeps login user-managed.
- Current reliability and live UI compatibility need separate verification before adoption.

Decision: document as an optional future backend, not the default path.

### `BoyuXiao/toutiao-auto-publisher`

Reference: https://github.com/BoyuXiao/toutiao-auto-publisher

Useful ideas:

- Targets `https://mp.toutiao.com/profile_v4/graphic/publish`, which is the same practical page this skill stages.
- Treats browser login state as the operational gate.
- Uses selector fallback/cache thinking so working selectors can be reused across runs.
- Fills Toutiao's `.ProseMirror` editor through browser-side DOM/JavaScript instead of relying only on keyboard typing.
- Makes image upload a separately verified step rather than assuming text staging means image staging succeeded.
- Treats publishing as a two-step UI flow: first `预览并发布`, then confirmation.
- Tracks published URLs in `published_articles.json` so interrupted batch jobs can resume without duplicating posts.
- Supports publish intervals to reduce suspicious high-frequency posting.

Limitations for this local skill:

- The upstream README describes immediate automatic publishing as a normal path; this local skill defaults to staged/autosaved review and requires explicit confirmation before final publish.
- The upstream implementation uses Selenium; this local skill should not use Selenium and should stay on `agent-browser` unless the user explicitly changes that constraint.
- The upstream article generation path is DeepSeek prompt based and uses 46LA hot topics; this skill keeps the stricter multi-source brief and verification contract.
- Upstream cookie export is a convenience path, but this skill keeps login user-managed unless the user explicitly provides a cookie file/profile.
- Upstream `markdown_to_html()` is intentionally simple and does not preserve local Markdown image markers; this skill keeps `payload.json` as the source of truth for local images.
- Upstream cover generation depends on Tencent Hunyuan credentials; this skill defaults to local HTML card visuals to avoid extra external API dependencies.

Decision: borrow only the workflow concepts (selector fallback, ProseMirror DOM path, publish-step separation, duplicate-publish records, interval awareness). Do not adopt Selenium as the execution layer.

### Official Open API

Reference: https://open.douyin.com/platform/resource/docs/ability/content-management/toutiao-publish-solution/

Finding:

- The official open API page is for direct video publishing to Toutiao.
- The documented limitation says it does not support Toutiao articles or micro-posts.

Decision: for articles and micro-posts, browser staging remains the practical path.

## Toutiao Format Heuristics

Treat live UI validation as the source of truth. Community tools and docs vary, but these defaults are useful:

- Article title: concise, normally 2-30 Chinese characters or equivalent units.
- Article body: at least 300 words; 800-3000 words is usually easier to read than very long text.
- Micro-post: keep under about 2000 Chinese characters; shorter is better for readability.
- Images: use local PNG/JPG/WebP/GIF where supported; avoid watermarks, fake screenshots, and misleading generated news photos.
- Article visuals: cover/lead image plus 1-2 inline visuals for a normal article.
- Structure: H1 title, short opening hook, section headings, short paragraphs, source section at the end.

## Visual Strategy

Use source-backed product screenshots or official images when available. If not, generate editorial cards:

- cover card: topic, tension, and 2-3 key points;
- context card: timeline, comparison, or "why it matters";
- takeaway card: practical conclusion or next steps.

Prefer infographic/concept cards over photorealistic generated news images.
