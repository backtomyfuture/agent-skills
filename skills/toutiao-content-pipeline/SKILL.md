---
name: toutiao-content-pipeline
description: 自动搜集信息、交叉验证信源、整理选题 brief、生成头条图文/微头条内容、处理发布格式，并暂存到今日头条/头条号/mp.toutiao.com 编辑器或在明确确认后发布。ALWAYS use this skill whenever the user mentions 今日头条, 头条号, toutiao, mp.toutiao.com, 微头条, 写文章, 发布到头条, 头条草稿, 内容自动生产线, Hermes 内容流水线, or asks to collect news/topics and turn them into Toutiao content. This skill is manually invoked and does not create cron jobs. Default to staged/autosaved editor state first; only final-publish when the user explicitly asks.
---

# Toutiao Content Pipeline

Use this skill to run a manual end-to-end Toutiao content workflow:

1. collect current information from multiple sources;
2. autonomously select the best current topic and angle;
3. verify and structure the information into a reusable brief;
4. draft articles or micro-posts for Toutiao;
5. generate visual assets so the article is not text-only;
6. format the content into editor-ready local files;
7. stage it in the Toutiao creator backend, using staged/autosaved editor state by default.

This skill combines the Hermes-style multi-agent content pipeline with the stricter "news intelligence" brief contract: the first half is about source quality, the second half is about safe publication.

## Operating Boundaries

- Do not create cron jobs, scheduled automations, background monitors, or recurring tasks. The user will trigger this skill from another tool.
- Login is user-managed. You may open `https://mp.toutiao.com/` and check whether the backend is logged in, but do not perform QR, phone, SMS, password, or cookie-recovery flows.
- Default to staged/autosaved editor state. Click final publish only when the user explicitly asks for immediate publication or has confirmed the final preview.
- Do not try to bypass platform rules, AI-content labeling, copyright checks, or risk controls. Improve readability and factuality; do not frame "removing AI smell" as evading detection.
- Treat generated content as assisted content. If platform UI provides AI-content labeling or declaration options, use them honestly when the content was substantially generated or rewritten by AI.
- Keep source URLs and verification notes. If a fact cannot be verified, mark it as unverified or remove it from the publishable draft.
- Toutiao's article editor may not expose a stable "save draft" button. Treat the normal safe state as **staged/autosaved in the editor**, and explicitly report this difference instead of promising a saved draft.
- Do not publish a dry text-only long article. For article mode, include at least one cover visual plus 1-2 inline images unless the user explicitly asks for text-only.

## Inputs

Accept any of these:

- a broad category, audience, and quantity request, such as "今天自动搜 AI Agent 热点，写一篇头条文章和两条微头条";
- a list of source URLs to research and transform;
- an existing Markdown file or brief JSON to publish;
- a user-provided article draft that only needs formatting and Toutiao staging.

If the user does not specify content type, produce one long article. If the user does not specify a topic, autonomously discover current hot topics. If the user asks for "微头条", "短内容", "多条", or a high-frequency distribution pack, produce micro-posts.

## Working Directory

Create a per-run workspace unless the user provides one:

```bash
mkdir -p /tmp/toutiao-content-pipeline/$(date +%Y%m%d-%H%M%S)
```

Save these artifacts as the run progresses:

- `brief.json` and `brief.md` for verified source material;
- `drafts/<slug>.md` for generated article or micro-post drafts;
- `visuals/` and `visual_plan.json` for cover and inline image assets;
- `payloads/<slug>/title.txt`, `body.txt`, and `payload.json` after formatting;
- `publish-log.md` with browser actions, draft status, and any unresolved risks.

## Phase 1: Intent Parse

Extract and write down:

- category or topic, or infer "current hot topics in the user's usual domain" when unspecified;
- time range, normally "latest/today/this week";
- target output: article, micro-post, or both;
- quantity;
- target reader;
- publication mode: draft, final publish, or "ask before final publish";
- source constraints: official sources only, Chinese/English mix, user-specified URLs, or broad web search.

For current news, latest topics, or anything time-sensitive, browse the web. Do not rely on memory for current facts. The default behavior is autonomous topic discovery: do not ask the user to provide an angle unless they explicitly request manual selection.

## Phase 2: Autonomous Topic Discovery

Collect candidates from diverse sources and current hot lists. Prefer sources that can be re-run manually by the agent, then supplement with web search:

- official announcements, company blogs, GitHub releases, arXiv/papers, regulator notices;
- 36Kr hot/news/search, Hacker News, GitHub Trending, Product Hunt, Reddit, X/Twitter, Weibo/Zhihu/Baidu/Toutiao hot lists as trend signals, not sole proof;
- Reuters/AP/BBC/Financial Times/Bloomberg/Caixin/The Paper/official media when available;
- broad web search for missing primary sources and counter-evidence.

If `opencli` is available, use it for hot-list style discovery after checking live help. Example pattern:

```bash
opencli list -f yaml
opencli 36kr -h
opencli 36kr hot -h
opencli 36kr hot --limit 10 -f yaml
```

If `opencli` reports `BROWSER_CONNECT` or another connector problem, fall back to web search and record the failure in `publish-log.md`.

Keep a candidate pool of 10-30 items. Each item should have a topic, source, source URL, freshness, rough heat signal, and initial risk note. Do not draft from the first attractive item; rank the pool first.

## Phase 3: News Intelligence

For each candidate, produce the fields in `references/contracts.md`:

- title;
- category;
- heat level;
- freshness;
- confidence;
- core facts;
- key numbers;
- background;
- source URLs;
- source notes;
- content angles;
- target platforms;
- visual opportunities;
- risk notes;
- follow-up questions.

Use these verification rules:

- Major factual claims need at least two independent sources, or one primary source plus clear caveat.
- Self-media reposts, CSDN/Juejin/community rankings, screenshots, and vendor marketing copy are weak evidence. They can support "industry discussion" or "reported by X", but they cannot support benchmark superiority, release timing, pricing, or market conclusions by themselves.
- Claims from a single weak/self-media source must be downgraded to `unverified` or removed from publishable copy. If kept, phrase them as source-limited claims, for example "该数据来自国内行业报告/自媒体整理，非官方背书".
- Distinguish confirmed facts, analysis, speculation, and rumors.
- Do not use anonymous screenshots or marketing-account reposts as factual sources unless they are explicitly marked as unverified.
- Keep domestic and overseas angles separate when they differ.
- Prefer fewer high-quality items over filling a quota with weak material.

## Phase 4: Auto Select Topic And Angle

Rank candidates by:

- source reliability;
- freshness and time window;
- audience relevance;
- content usefulness;
- platform risk;
- visual potential: can the topic support a meaningful cover, timeline, comparison card, or data card;
- novelty compared with the user's previous output if known.

Write `brief.md` in this structure:

```markdown
# 今日头条内容 brief

## 推荐选题
### 1. [title]
- 类型:
- 热度:
- 时效:
- 可信度:
- 信源质量:
- 核心事实:
- 关键数据:
- 背景:
- 各方反应:
- 影响分析:
- 推荐内容方向:
- 目标平台:
- 关键词:
- 信息来源:
- 风险备注:
- 发布决策:
- 视觉素材机会:

## 速览
| # | 标题 | 类型 | 可信度 | 推荐理由 | 风险 |
```

Select the strongest topic and angle yourself by default. Only pause for user choice when:

- the user explicitly asks to choose from options;
- two candidates are equally strong but imply very different risk profiles;
- the chosen angle touches sensitive categories where the user's risk tolerance matters.

When autonomous selection is used, write this compact note into `brief.md` and `publish-log.md`:

```markdown
自动选题结果:
- 选题:
- 角度:
- 为什么选它:
- 为什么没有选其他高热候选:
- 主要风险:
```

## Phase 5: Draft Content

For long articles:

- Start with a concrete scene, conflict, or consequence rather than a generic opening.
- Use the verified facts from `brief.json`; do not invent numbers, quotes, or reactions.
- Include source attribution naturally when a claim depends on a specific report.
- Keep paragraphs short for mobile reading.
- Add a clear conclusion or practical takeaway.
- Plan image positions while drafting: cover after H1, one context image after the opening section, and one summary/data card near the middle or before the conclusion.

For micro-posts:

- Make each post self-contained.
- Keep one core point per post.
- Use a hook, verified fact, and takeaway.
- Avoid overusing hashtags; prefer keywords that match the topic.

Drafts should be Markdown files under `drafts/`. Each file should begin with an H1 title unless it is a micro-post with no separate title.

## Phase 6: Visual Assets

For article mode, create visual assets before formatting. Use this priority order:

1. **Source-backed images** from official pages, press kits, GitHub/social cards, product screenshots, charts, or user-provided assets, when license and context are acceptable.
2. **Generated visual cards** using the bundled HTML-card helper. This is the default fallback because it creates useful cover/context visuals without depending on external image APIs.
3. **Toutiao editor assets** such as AI recommended inline images and free stock cover images, based on current UI availability.
4. **AI-generated bitmap images** only when an image generation tool is available and the prompt can avoid misleading news-photo realism.

Never invent documentary/news photos. If a visual is generated, make it an infographic, concept card, timeline, comparison card, or abstract editorial image rather than a fake event photo.

Run the helper:

```bash
python3 /Users/jarod/.agents/skills/toutiao-content-pipeline/scripts/create_toutiao_visuals.py \
  '/tmp/toutiao-content-pipeline/<run>/drafts/<slug>.md' \
  --output-dir '/tmp/toutiao-content-pipeline/<run>/visual-output'
```

Then render the generated HTML cards to PNG:

```bash
agent-browser --session-name toutiao-visual --allow-file-access open 'file:///abs/path/visuals/cover.html'
agent-browser --session-name toutiao-visual screenshot '#card' '/abs/path/visuals/cover.png'
agent-browser --session-name toutiao-visual --allow-file-access open 'file:///abs/path/visuals/inline-1.html'
agent-browser --session-name toutiao-visual screenshot '#card' '/abs/path/visuals/inline-1.png'
agent-browser --session-name toutiao-visual --allow-file-access open 'file:///abs/path/visuals/inline-2.html'
agent-browser --session-name toutiao-visual screenshot '#card' '/abs/path/visuals/inline-2.png'
```

Continue with `draft_with_visuals.md` from the helper, not the original text-only draft. Verify:

```bash
find '/tmp/toutiao-content-pipeline/<run>/visual-output/visuals' -name '*.png' -size +0
rg -n '!\[.*\]\(' '/tmp/toutiao-content-pipeline/<run>/visual-output/draft_with_visuals.md'
```

If image rendering fails, stop and report the blocker. Do not proceed to a text-only article unless the user explicitly approves.

## Phase 7: Review Gate

Do not move to browser staging until the draft passes this checklist. Write a short Review Gate result into `publish-log.md` before opening or filling the Toutiao editor.

- The title and body match the verified facts.
- Every factual claim with risk has a source.
- Unverified or speculative claims are removed or labeled.
- The content does not copy long passages from sources.
- The content does not promise certainty where sources disagree.
- AI-generated or AI-assisted content labeling is handled honestly if the platform asks.
- Sensitive categories such as finance, medicine, law, politics, public emergencies, minors, disasters, and personal data get extra caution.
- Article mode includes meaningful images: at least 1 cover/lead image and normally 1-2 inline visuals. Each visual should support the nearby section, not act as decoration.

If the user asked for final publish, summarize the title, output type, source count, risk notes, and draft path before clicking final publish.

## Phase 8: Format For Toutiao

Use the helper script for deterministic formatting:

```bash
python3 /Users/jarod/.agents/skills/toutiao-content-pipeline/scripts/prepare_toutiao_payload.py \
  '/abs/path/to/draft.md' \
  --mode article \
  --output-dir '/tmp/toutiao-content-pipeline/<run>/payloads/<slug>'
```

For micro-posts:

```bash
python3 /Users/jarod/.agents/skills/toutiao-content-pipeline/scripts/prepare_toutiao_payload.py \
  '/abs/path/to/micro-post.md' \
  --mode weitoutiao \
  --output-dir '/tmp/toutiao-content-pipeline/<run>/payloads/<slug>'
```

The script writes:

- `title.txt`;
- `body.txt`;
- `payload.json`;
- image markers such as `[[IMG_1]]` when the source Markdown contains local images.

Read `payload.json` before browser staging. Stop if it reports missing local images or a micro-post body that is too long.

## Phase 9: Stage In Toutiao

Use a browser automation skill/tool when available. Prefer `agent-browser` in this environment because it preserves a reusable profile and lets the user log in manually.

Recommended entry points:

- Article editor: `https://mp.toutiao.com/profile_v4/graphic/publish`
- Micro-post editor: `https://mp.toutiao.com/profile_v4/weitoutiao/publish`
- Generic backend: `https://mp.toutiao.com/`

Open the editor:

```bash
agent-browser --headed true --session-name toutiao open "https://mp.toutiao.com/profile_v4/graphic/publish"
```

If the page shows a login state, stop and ask the user to complete login in the headed browser. Continue in the same session after they confirm.

Use live page inspection before interacting:

```bash
agent-browser --session-name toutiao snapshot -i
```

### `agent-browser` command notes

- Snapshot refs must be used as `@e114`, not `--ref e114`.
- Refs are ephemeral. After every new `snapshot -i`, use the latest visible ref; do not reuse old refs such as `@e27` if the next snapshot changed it to `@e15`.
- Screenshot syntax is `agent-browser --session-name toutiao screenshot [selector] [path]`. The selector is optional, but when present it comes before the path. Do not use `--full-page false`.
- There is no `agent-browser evaluate` subcommand. The command name is `eval`, but browser staging verification should not depend on custom JS because editor internals can change. Prefer `snapshot`, `keyboard inserttext`, `screenshot`, and local file checks.

Examples:

```bash
agent-browser --session-name toutiao click @e114
agent-browser --session-name toutiao screenshot /tmp/toutiao-page.png
agent-browser --session-name toutiao screenshot @e15 /tmp/toutiao-editor.png
```

Then fill the visible form:

- For article mode, fill the title from `title.txt` and the body from `body.txt`.
- For micro-post mode, fill the main text from `body.txt`; only use `title.txt` if the page exposes a title-like field.
- For images, replace `[[IMG_N]]` markers with the corresponding local file upload when the editor supports inline images. If the UI only supports cover images, ask the user whether to upload as cover or keep text-only.
- If the editor exposes AI recommended images or free stock cover library, use it as a supplement when local inline upload is unreliable. This pattern is documented in `references/toutiao-tools.md`; verify the current UI before clicking.
- Do not assume selectors. Use current snapshot refs, visible labels, and post-action verification.
- For contenteditable/rich-text editors, click the current editor ref and immediately run `keyboard inserttext` from `body.txt`. If the first snapshot still shows the placeholder, take a fresh `snapshot -i`, click the new editor ref, and immediately insert again.

Example:

```bash
agent-browser --session-name toutiao click @e15
agent-browser --session-name toutiao keyboard inserttext "$(cat '/tmp/toutiao-content-pipeline/<run>/payloads/<slug>/body.txt')"
```

### ProseMirror staging helper

If keyboard insertion leaves the body placeholder unchanged, duplicates stale text, or corrupts image markers, use the agent-browser-only helper. Do not use Selenium for this skill. The helper borrows the reusable ideas from `BoyuXiao/toutiao-auto-publisher` (selector fallback thinking, staging verification, publish-step separation) but executes through `agent-browser` and the live Toutiao ProseMirror editor only.

Default staged/autosaved run:

```bash
python3 /Users/jarod/.agents/skills/toutiao-content-pipeline/scripts/stage_toutiao_payload_agent_browser.py \
  '/tmp/toutiao-content-pipeline/<run>/payloads/<slug>/payload.json' \
  --session-name toutiao \
  --open
```

Use `--skip-images` only when image upload is blocked and the user approves text/cover-only staging. The helper never clicks final publish.

Helper behavior:

- Opens the article editor when `--open` is passed, otherwise reuses the current `agent-browser` session.
- Fills the title from `payload.json`.
- Uses the Toutiao editor's ProseMirror-backed `setHTML` path to replace stale editor content cleanly.
- For each local image marker such as `[[IMG_1]]`, selects that exact marker through the editor selection and attempts upload through the live image dialog using `agent-browser upload`.
- Prints a JSON result with `status`, `image_results`, editor stats, and `final_publish_clicked=false`.

Keep this helper scoped to staging. It must not bypass login, platform rules, AI-content labeling, copyright checks, or risk controls.

Save or publish:

- If the user did not explicitly ask for final publish, leave the filled editor open for review and report the status as `staged_autosaved`.
- Toutiao currently may show only `预览`, `定时发布`, and `预览并发布`, with no explicit `保存草稿` button. Do not click any publish-like button just to create a draft.
- If there is no draft button but the page autosaves, verify the editor still contains the inserted content and tell the user this is autosave/staging, not a guaranteed saved draft button.
- If the user explicitly asked for final publish, click final publish only after the review gate summary.

## Verification

After staging or publishing, record:

- editor URL;
- article or micro-post mode;
- title;
- body character count;
- image count;
- source count;
- status: staged_autosaved, saved_draft, final_published, or blocked;
- unresolved risks or user action required.

For long bodies, do not rely on the top of `snapshot` output. It often truncates rich editor content. Verify by sampling opening, middle, and ending phrases from `body.txt`; at minimum include the ending "参考来源" or equivalent source section when present.

Example:

```bash
rg -n "开篇关键句|中段关键句|参考来源" '/tmp/toutiao-content-pipeline/<run>/payloads/<slug>/body.txt'
agent-browser --session-name toutiao snapshot -i > '/tmp/toutiao-editor-snapshot.txt'
rg -n "开篇关键句|参考来源" '/tmp/toutiao-editor-snapshot.txt' || true
```

If `snapshot` only proves the opening content, report verification as "payload complete; editor opening confirmed; long-body full DOM length not available through current agent-browser CLI" instead of overstating certainty.

Report concise results to the user, including the payload directory and whether final publish was clicked.

## Fallbacks

- If web search is unavailable, ask the user for source URLs or a local brief before drafting. Do not fabricate current news.
- If `agent-browser` is unavailable, use the available browser automation tool for headed login and form filling. If no browser automation is available, stop after producing `payload.json`.
- If Toutiao changes its UI, inspect the live page and adapt. Do not keep retrying stale selectors.
- If the account lacks article/micro-post publishing permissions, report the blocker and leave the payload files ready.

## References

- `references/contracts.md` defines the brief and payload schema.
- `references/research.md` records the source ideas behind this skill and the current public Toutiao entry points.
- `references/toutiao-tools.md` summarizes existing Toutiao automation tools and format heuristics found during research.
