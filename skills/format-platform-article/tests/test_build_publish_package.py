import json
import re
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import build_publish_package  # noqa: E402
import zhihu_md2zhihu  # noqa: E402


def fake_zhihu_convert(source_md, dest_md, *, asset_repo=None, platform="zhihu", download=True, md2zhihu_bin=None, **_):
    """Stand-in for md2zhihu: rewrites local image links to fake git-hosted URLs.

    Mirrors the real wrapper's contract — write the converted Markdown to
    ``dest_md`` and return a ``ConvertResult`` — so build_zhihu_markdown can be
    exercised without installing md2zhihu or pushing to a real git repo.
    """
    dest = Path(dest_md)
    dest.parent.mkdir(parents=True, exist_ok=True)
    src_text = Path(source_md).read_text(encoding="utf-8")
    converted = re.sub(
        r"\]\(assets/([^)]+)\)",
        r"](https://gitee.example.com/u/bed/raw/branch/\1)",
        src_text,
    )
    dest.write_text("<!-- md2zhihu -->\n" + converted, encoding="utf-8")
    return zhihu_md2zhihu.ConvertResult(ok=True, md_output=dest, asset_repo=asset_repo)


class BuildPublishPackageTests(unittest.TestCase):
    def test_extract_title_and_body_uses_h1(self):
        title, body, warnings = build_publish_package.extract_title_and_body("# 标题\n\n正文", Path("article.md"))

        self.assertEqual(title, "标题")
        self.assertEqual(body, "正文")
        self.assertEqual(warnings, [])

    def test_extract_title_and_body_uses_filename_without_h1(self):
        title, body, warnings = build_publish_package.extract_title_and_body("正文", Path("my-article.md"))

        self.assertEqual(title, "my-article")
        self.assertEqual(body, "正文")
        self.assertEqual(warnings[0]["code"], "missing_h1")

    def test_rewrite_images_to_assets_copies_local_image(self):
        fixture_dir = Path(__file__).resolve().parent / "fixtures"
        with tempfile.TemporaryDirectory() as tmp:
            assets = Path(tmp) / "assets"
            markdown, copied, warnings = build_publish_package.rewrite_images_to_assets(
                "![alt](./media/sample.png)",
                fixture_dir,
                assets,
            )

            self.assertEqual(markdown, "![alt](assets/sample.png)")
            self.assertTrue((assets / "sample.png").exists())
            self.assertEqual(copied[0]["output"], "assets/sample.png")
            self.assertEqual(warnings, [])

    def test_rewrite_images_to_assets_downloads_remote_image_by_default(self):
        # Notion exports embed presigned S3 URLs that expire within an hour;
        # the builder must materialize them into assets/ so the cross-platform
        # HTML files keep working after the URL expires.
        png_bytes = b"\x89PNG\r\n\x1a\nfakepng"
        fixture_dir = Path(__file__).resolve().parent / "fixtures"

        def fake_downloader(url, assets_dir, index):
            self.assertTrue(url.startswith("https://prod-files-secure.s3"))
            self.assertEqual(index, 1)
            target = assets_dir / f"remote_{index:02d}.png"
            target.write_bytes(png_bytes)
            return target

        with tempfile.TemporaryDirectory() as tmp:
            assets = Path(tmp) / "assets"
            markdown, copied, warnings = build_publish_package.rewrite_images_to_assets(
                "![alt](https://prod-files-secure.s3.us-west-2.amazonaws.com/abc/image.png?X-Amz-Expires=3600)",
                fixture_dir,
                assets,
                remote_downloader=fake_downloader,
            )

            self.assertEqual(markdown, "![alt](assets/remote_01.png)")
            self.assertTrue((assets / "remote_01.png").exists())
            self.assertEqual(assets.joinpath("remote_01.png").read_bytes(), png_bytes)
            self.assertEqual(copied[0]["output"], "assets/remote_01.png")
            self.assertEqual(warnings, [])

    def test_rewrite_images_to_assets_emits_warning_when_remote_download_fails(self):
        fixture_dir = Path(__file__).resolve().parent / "fixtures"

        def failing_downloader(url, assets_dir, index):
            return None

        with tempfile.TemporaryDirectory() as tmp:
            assets = Path(tmp) / "assets"
            original = "![alt](https://prod-files-secure.s3.us-west-2.amazonaws.com/abc/image.png?X-Amz-Expires=3600)"
            markdown, copied, warnings = build_publish_package.rewrite_images_to_assets(
                original,
                fixture_dir,
                assets,
                remote_downloader=failing_downloader,
            )

            self.assertEqual(markdown, original)
            self.assertEqual(copied, [])
            self.assertEqual(len(warnings), 1)
            self.assertEqual(warnings[0]["code"], "remote_image_download_failed")
            self.assertIn("prod-files-secure", warnings[0]["target"])

    def test_rewrite_images_to_assets_keeps_legacy_behavior_when_download_disabled(self):
        fixture_dir = Path(__file__).resolve().parent / "fixtures"
        with tempfile.TemporaryDirectory() as tmp:
            assets = Path(tmp) / "assets"
            original = "![alt](https://example.com/remote.png)"
            markdown, copied, warnings = build_publish_package.rewrite_images_to_assets(
                original,
                fixture_dir,
                assets,
                download_remote=False,
            )

            self.assertEqual(markdown, original)
            self.assertEqual(copied, [])
            self.assertEqual(len(warnings), 1)
            self.assertEqual(warnings[0]["code"], "remote_image")

    def test_remote_image_extension_handles_notion_presigned_urls(self):
        ext = build_publish_package._remote_image_extension(
            "https://prod-files-secure.s3.us-west-2.amazonaws.com/abc/image.png?X-Amz-Expires=3600",
            "binary/octet-stream",
        )

        self.assertEqual(ext, ".png")

    def test_remote_image_extension_falls_back_to_content_type(self):
        ext = build_publish_package._remote_image_extension(
            "https://cdn.example.com/blob?token=xyz",
            "image/jpeg",
        )

        self.assertEqual(ext, ".jpg")

    def test_build_package_downloads_remote_images_into_assets(self):
        # End-to-end smoke test: the build pipeline should call the injected
        # remote_downloader, copy bytes into assets/, and emit an HTML that
        # references the new local path instead of the original URL.
        fixture = Path(__file__).resolve().parent / "fixtures" / "article.md"
        png_bytes = b"\x89PNG\r\n\x1a\nfakepng"

        def fake_downloader(url, assets_dir, index):
            target = assets_dir / f"remote_{index:02d}.png"
            target.write_bytes(png_bytes)
            return target

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "article.publish"
            report = build_publish_package.build_package(
                fixture,
                output,
                overwrite=False,
                strict=False,
                table_mode="never",
                style="magazine",
                remote_downloader=fake_downloader,
            )

            # The remote image in the fixture must now live under assets/.
            self.assertTrue((output / "assets" / "remote_01.png").exists())
            asset_paths = {a["output"] for a in report["assets"]}
            self.assertIn("assets/remote_01.png", asset_paths)

            # No remote-leftover warnings should be emitted.
            warning_codes = [item["code"] for item in report["warnings"]]
            self.assertNotIn("remote_image", warning_codes)
            self.assertNotIn("remote_image_download_failed", warning_codes)

            # WeChat embeds the new asset as Base64 (not the original https URL).
            wechat_html = (output / "wechat.html").read_text(encoding="utf-8")
            self.assertNotIn("example.com/remote.png", wechat_html)
            self.assertIn("data:image/png;base64,", wechat_html)

            # Zhihu's Markdown fallback (no asset repo) must reference the local
            # asset, not the original (often-expiring) URL.
            zhihu_md = (output / "platforms" / "zhihu.md").read_text(encoding="utf-8")
            self.assertNotIn("example.com/remote.png", zhihu_md)
            self.assertIn("../assets/remote_01.png", zhihu_md)

    def test_blockquote_with_callout_marker_renders_as_callout_badge(self):
        # `> ⚠️ **注意** ：...` is the common Notion / source pattern. The
        # WeChat renderer must NOT show this as a literary curly-quote block —
        # those should be reserved for actual citations. Callout markers
        # inside a blockquote should render with the same badge layout as a
        # bare `⚠️ ...` paragraph, and the body must not duplicate the badge
        # label (no leftover "**注意**：" prefix).
        rendered = build_publish_package.render_wechat_html(
            "标题",
            "> ⚠️  **注意** ：这个价格可能是限时机制，建议先试试，抓紧窗口期。",
        )

        # Badge style of render_callout — a readable bold terracotta title, not
        # a tiny letter-spaced uppercase eyebrow (uppercase is meaningless for
        # Chinese and wide tracking makes it look sparse).
        self.assertIn("background:#fdf6ec", rendered)
        self.assertIn("border-left:3px solid #c2410c", rendered)
        self.assertNotIn("text-transform:uppercase", rendered)
        self.assertIn("font-size:16px;font-weight:700", rendered)
        self.assertIn("注意", rendered)
        # Body keeps the content but drops the redundant **注意** ： prefix.
        self.assertIn("这个价格可能是限时机制", rendered)
        self.assertNotIn("**注意**", rendered)
        # No literary curly-quote glyph or italic when it is actually a callout.
        self.assertNotIn("&ldquo;", rendered)
        self.assertNotIn("font-style:italic", rendered)

    def test_notion_style_callout_with_emoji_and_nested_quote_marker(self):
        # Notion exports callouts as `> <emoji> >  **标签** ：body`. The renderer
        # must:
        # - treat the leading emoji as a callout marker (no literary curly-quote),
        # - strip Notion's second `>` separator so it does not show up as text,
        # - promote the bold prefix into the badge label (so "震撼" becomes the
        #   badge instead of being shown twice — once as bold text, once not),
        # - never leak the `>` character or the literal `**实测震撼**` into the
        #   body of the rendered HTML.
        rendered = build_publish_package.render_wechat_html(
            "标题",
            "> 😱 >  **实测震撼** ：刚上去看了一眼，吓我一跳——「82,000,000,000」！",
        )

        self.assertIn("background:#fdf6ec", rendered)
        self.assertIn("border-left:3px solid #c2410c", rendered)
        # Badge shows the emoji + the bold-promoted custom label.
        self.assertIn("😱", rendered)
        self.assertIn("实测震撼", rendered)
        # Body contains the real content, without the Notion artifacts.
        self.assertIn("刚上去看了一眼", rendered)
        self.assertIn("82,000,000,000", rendered)
        self.assertNotIn("**实测震撼**", rendered)
        self.assertNotIn("&gt;", rendered)
        self.assertNotIn("&ldquo;", rendered)
        self.assertNotIn("font-style:italic", rendered)

    def test_notion_style_callout_gift_marker_uses_custom_bold_label(self):
        rendered = build_publish_package.render_wechat_html(
            "标题",
            "> 🎁 >  **福利** ：我的 Max 套餐送了 820 亿 Token，欢迎加小圈领取 ⬇️",
        )

        self.assertIn("🎁", rendered)
        self.assertIn("福利", rendered)
        self.assertIn("820 亿 Token", rendered)
        self.assertIn("欢迎加小圈领取", rendered)
        self.assertNotIn("**福利**", rendered)
        self.assertNotIn("&gt;", rendered)
        self.assertNotIn("&ldquo;", rendered)

    def test_notion_style_callout_cleanup_covers_article_marker_emojis(self):
        markdown = "\n\n".join(
            [
                "> 🧰 >  **这篇文章先看大趋势** 指标二、三需要用脚本逐周计算。",
                "> 📏 >  **先把口径说在前面:** 下面这张对照表只用来看方向。",
                "> 🟢 >  **绿灯 · 主线还在加速** 付费 Token 三条线同时向上。",
                "> 🟡 >  **黄灯 · 只是流量热闹** 免费模型涨得欢。",
                "> 🔴 >  **红灯 · 准备防守** Token 增长明显放缓。",
            ]
        )

        wechat = build_publish_package.render_wechat_html("标题", markdown)
        toutiao = build_publish_package.render_toutiao_html("标题", markdown)
        zsxq = build_publish_package.render_zsxq_html("标题", markdown)

        for rendered in (wechat, toutiao, zsxq):
            self.assertNotIn("&gt;", rendered)
            self.assertNotIn("**这篇文章先看大趋势**", rendered)
            self.assertNotIn("**绿灯 · 主线还在加速**", rendered)
            self.assertIn("这篇文章先看大趋势", rendered)
            self.assertIn("绿灯 · 主线还在加速", rendered)

        self.assertIn("background:#fdf6ec", wechat)
        # Zsxq callouts render as a clean bold label line (no inline ▍ bar).
        self.assertIn("<strong>🟢 绿灯 · 主线还在加速</strong>", zsxq)

    def test_blockquote_without_callout_marker_renders_clean_quote_card(self):
        # Plain blockquote (no warning marker) renders as a warm cream card with
        # a terracotta left rule and italic body. The big serif “/” glyphs were
        # removed on purpose — readers found them distracting and the left rule +
        # italic already read as a quotation.
        rendered = build_publish_package.render_wechat_html(
            "标题",
            "> 把记忆当成资产，而不是日志。",
        )

        self.assertNotIn("&ldquo;", rendered)
        self.assertNotIn("&rdquo;", rendered)
        self.assertIn("background:#fdf6ec", rendered)
        self.assertIn("border-left:3px solid #c2410c", rendered)
        self.assertIn("font-style:italic", rendered)
        self.assertIn("把记忆当成资产", rendered)

    def test_render_wechat_html_has_no_auto_header(self):
        # The user authors the title in the WeChat editor's title field and any
        # intro paragraph in the source Markdown. The renderer must NOT inject
        # an H1, gradient header, reading-time line, or "本文路线" outline.
        rendered = build_publish_package.render_wechat_html("标题", "## 小节\n\n> 引用")

        self.assertNotIn("linear-gradient(135deg,#0f172a", rendered)
        self.assertNotIn("linear-gradient(90deg,#eef4ff", rendered)
        self.assertNotIn("本文路线", rendered)
        self.assertNotIn("<h1", rendered)
        # Authored content still renders inside a quote container — the
        # editorial redesign uses <section> instead of raw <blockquote> but the
        # quoted text and an attribution marker must both be present.
        self.assertIn("引用", rendered)
        self.assertIn("border-left:3px solid #c2410c", rendered)
        self.assertIn("小节", rendered)

    def test_render_wechat_html_body_does_not_force_mobile_overflow(self):
        rendered = build_publish_package.render_wechat_html("标题", "## 小节\n\n正文")

        self.assertIn("<body style=\"box-sizing:border-box;", rendered)
        self.assertIn("padding:20px 0", rendered)
        self.assertIn("width:calc(100% - 32px)", rendered)
        self.assertIn("overflow-x:hidden", rendered)
        self.assertNotIn("<body style=\"width:100%;", rendered)

    def test_render_wechat_html_uses_editorial_heading_and_quote_styles(self):
        rendered = build_publish_package.render_wechat_html(
            "标题",
            "## 一级小节\n\n### 操作步骤\n\n> 如果不幸封号也不用慌张，退款基本都能追回。\n\n💡 这是一条提示。",
        )

        # Stale colors from earlier iterations must be gone.
        for stale_color in [
            "#ecfdf5",
            "#10b981",
            "#047857",
            "#0f766e",
            "#064e3b",
            "#a7f3d0",
            "rgba(15,118,110",
            # Old WeChat treatments dropped in favor of the editorial column.
            "border-left:5px solid #d97706",
            "background:#111827",
            "border-left:4px solid #f59e0b",
            "background:#fff7ed",
            "border-left:4px solid #d97706",
            "box-shadow:0 8px 22px rgba(17,24,39,0.06)",
        ]:
            self.assertNotIn(stale_color, rendered)
        # The new H2 is a clean editorial title with an accent block prefix and
        # a thin bottom hairline (not a heavy left bar).
        self.assertIn("border-bottom:1px solid #ece4d6", rendered)
        self.assertIn("background:#c2410c", rendered)
        self.assertIn("background:transparent", rendered)
        # The new H3 sheds the dark filled box for a marker + soft underline.
        self.assertIn("border-bottom:2px solid #fde68a", rendered)
        # The new blockquote uses warm cream + deep terracotta accents.
        self.assertIn("background:#fdf6ec", rendered)
        self.assertIn("border-left:3px solid #c2410c", rendered)
        self.assertIn("color:#3c2a14", rendered)
        # Callout label is rendered (marker + Chinese label, separated for
        # editorial uppercase tracking).
        self.assertIn(">💡<", rendered)
        self.assertIn("提示", rendered)

    def test_image_caption_paragraph_is_rendered_as_clean_italic(self):
        # Image captions written as "*▼ ...*" should not leak raw asterisks; they
        # should turn into a clean centered editorial caption (small grey italic
        # with a soft accent arrow), not a pill/tag chip.
        rendered = build_publish_package.render_wechat_html("标题", "*▼ 更新 Codex 后的入口*")

        self.assertNotIn("*▼", rendered)
        self.assertIn(">▼<", rendered)
        self.assertIn("更新 Codex 后的入口", rendered)
        # No tag-style pill; captions read as quiet editorial annotations.
        self.assertNotIn("border-radius:999px", rendered)
        self.assertIn("color:#8a8a8a", rendered)
        self.assertIn("text-align:center", rendered)

    def test_inline_italic_is_rendered_as_em(self):
        # Single-asterisk emphasis should render as <em> instead of staying as
        # literal asterisks in the output.
        rendered = build_publish_package.render_wechat_html("标题", "正文 *强调内容* 结束")

        self.assertIn("<em", rendered)
        self.assertIn(">强调内容</em>", rendered)
        self.assertNotIn("*强调内容*", rendered)

    def test_inline_bold_still_works_alongside_italic(self):
        # The italic regex must not accidentally swallow ** bold ** markers.
        # Bold is weight + deep near-black only (no amber underline) so a
        # bold-heavy article does not turn into a wall of underlines.
        rendered = build_publish_package.render_wechat_html("标题", "**重要** 和 *次要*")

        self.assertIn("font-weight:700", rendered)
        self.assertNotIn("border-bottom:2px solid #fcd34d", rendered)
        self.assertIn(">重要</span>", rendered)
        self.assertIn(">次要</em>", rendered)

    def test_render_wechat_html_handles_lists_dividers_and_callouts(self):
        rendered = build_publish_package.render_wechat_html(
            "标题",
            "第一段导语。\n\n- 准备账号\n- 准备信用卡\n\n---\n\n⚠️ 不要开启付费升级。",
        )

        # Unordered list items render as standalone paragraphs led by a real "•"
        # glyph — <ul>/<li> are dropped because WeChat mangles them on paste, and
        # a CSS-shape dot (empty styled span) gets stripped too, so we use a
        # literal bullet character that always survives.
        self.assertIn("准备账号", rendered)
        self.assertIn("准备信用卡", rendered)
        self.assertIn(">•</span>", rendered)
        self.assertNotIn("border-radius:50%", rendered)
        # Divider is the editorial three-dot pause, not raw dashes or <hr>.
        self.assertIn("● ● ●", rendered)
        self.assertIn("color:#c2a874", rendered)
        self.assertNotIn(">—</p>", rendered)
        self.assertNotIn("height:1px", rendered)
        self.assertNotIn("<hr", rendered)
        # Callout label survives.
        self.assertIn("注意", rendered)
        self.assertNotIn(">---<", rendered)

    def test_render_wechat_html_keeps_ordered_lists_readable_around_images(self):
        rendered = build_publish_package.render_wechat_html(
            "标题",
            "## 步骤\n\n1. 第一步\n![图](assets/a.png)\n\n1. 第二步\n1. 第三步",
        )

        # Editorial ordered lists use zero-padded numbers ("01.") in the accent
        # color, with the number rendered directly adjacent to the item text.
        self.assertIn("01.</span>第一步", rendered)
        self.assertIn("02.</span>第二步", rendered)
        self.assertIn("03.</span>第三步", rendered)
        self.assertNotIn('start="2"', rendered)

    def test_render_wechat_html_renders_markdown_tables(self):
        rendered = build_publish_package.render_wechat_html(
            "标题",
            "| 阈值 | 动作 |\n| --- | --- |\n| 50% | 邮件提醒 |\n| 100% | 检查资源 |",
        )

        self.assertIn("<table", rendered)
        self.assertIn("<th", rendered)
        self.assertIn("<td", rendered)
        self.assertIn("邮件提醒", rendered)
        self.assertNotIn("| --- |", rendered)

    def test_render_wechat_html_uses_image_placeholders_by_default(self):
        rendered = build_publish_package.render_wechat_html("标题", "![Image](assets/a.png)")

        self.assertIn("图片占位 1", rendered)
        self.assertIn("assets/a.png", rendered)
        self.assertNotIn("<figure", rendered)
        self.assertNotIn("<img", rendered)

    def test_render_wechat_preview_can_keep_inline_images_without_frames(self):
        rendered = build_publish_package.render_wechat_html("标题", "![架构图](assets/a.png)", image_mode="inline")

        self.assertIn("<img", rendered)
        self.assertIn("架构图", rendered)
        self.assertNotIn("<figure", rendered)

    def test_generated_table_image_skips_duplicate_caption_and_uses_subtle_frame(self):
        rendered = build_publish_package.render_wechat_html(
            "标题",
            "![二、新模型：两条线，解决不同问题](assets/tables/table_01_二新模型两条线解决不同问题.png)",
            image_mode="inline",
        )

        self.assertIn('alt="二、新模型：两条线，解决不同问题"', rendered)
        # Table images get a soft warm hairline frame and a low-key shadow that
        # matches the editorial palette (no harsh cool-grey border).
        self.assertIn("border:1px solid #ece4d6", rendered)
        self.assertIn("box-shadow:0 6px 18px rgba(120,80,30,0.06)", rendered)
        # The H2 already names the section — never repeat it as a pill caption
        # below the image.
        self.assertNotIn("二、新模型：两条线，解决不同问题</span></p>", rendered)
        self.assertNotIn("border-radius:999px", rendered)

    def test_render_wechat_embedded_can_inline_local_image_data(self):
        fixture_dir = Path(__file__).resolve().parent / "fixtures"
        rendered = build_publish_package.render_wechat_html(
            "标题",
            "![架构图](media/sample.png)",
            image_mode="data",
            asset_base_dir=fixture_dir,
        )

        self.assertIn('src="data:image/png;base64,', rendered)
        self.assertIn("<img", rendered)
        self.assertNotIn("media/sample.png", rendered)

    def test_render_code_block_uses_light_copy_safe_style(self):
        rendered = build_publish_package.render_wechat_html("标题", "```yaml\nserver: example\n```")

        # The code block stays light (Base64-paste friendly) and is wrapped in
        # the warm editorial card with a deep-amber accent rule. The language
        # label is rendered as a small uppercase header above the code, not as
        # literal text inside the <pre>.
        self.assertIn("background:#faf6ed", rendered)
        self.assertIn("color:#1a1a1a", rendered)
        self.assertIn("display:block", rendered)
        self.assertIn("white-space:pre-wrap", rendered)
        self.assertIn("server: example", rendered)
        self.assertIn(">yaml<", rendered)
        self.assertNotIn("color:#e5e7eb", rendered)

    def test_render_code_block_preserves_line_breaks_inside_code_element(self):
        rendered = build_publish_package.render_wechat_html(
            "标题",
            "```yaml\nserver: 34.82.100.50\nuuid: a1b2\nreality-opts:\n  public-key: abc\n```",
        )

        self.assertIn("server: 34.82.100.50\nuuid: a1b2\nreality-opts:\n  public-key: abc", rendered)
        self.assertIn("white-space:pre-wrap", rendered)

    def test_render_code_block_highlights_cjk_placeholders(self):
        rendered = build_publish_package.render_wechat_html(
            "标题",
            "```text\nvless://【UUID】@【服务器IP】:443#【备注】\nserver: 【你的服务器IP】\n```",
        )

        self.assertIn("vless://", rendered)
        self.assertIn("placeholder", rendered)
        self.assertIn("【UUID】", rendered)
        self.assertIn("【服务器IP】", rendered)
        self.assertIn("【备注】", rendered)
        self.assertIn("server: ", rendered)
        self.assertNotIn("[SERVER-IP]", rendered)

    def test_render_xueqiu_flavor_uses_only_supported_elements(self):
        # 雪球's editor strips <blockquote>/<ul>/<hr>, so the xueqiu flavor emits
        # bold-label callout paragraphs, "•" bullet paragraphs and a "● ● ●" text
        # divider — never those elements.
        rendered = build_publish_package.render_platform_html(
            "xueqiu",
            "标题",
            "## 小节\n\n💡 **核心** 这是提示内容。\n\n- 第一点\n- 第二点\n\n---\n\n正文段落。",
            image_mode="data",
        )
        self.assertIn("<title>标题 - 雪球长文粘贴版</title>", rendered)
        self.assertNotIn("<blockquote", rendered)
        self.assertNotIn("<ul>", rendered)
        self.assertNotIn("<hr", rendered)
        self.assertIn("● ● ●", rendered)
        self.assertIn("<p>• 第一点</p>", rendered)
        self.assertIn("<p><strong>💡 核心：</strong>这是提示内容。</p>", rendered)

    def test_render_platform_html_uses_native_layout(self):
        # Toutiao / SMZDM use conservative native markup (their editors strip the
        # magazine's decorative CSS). Headings are bare <h2>, quotes are native
        # <blockquote>, and placeholder image mode never inlines base64.
        rendered = build_publish_package.render_platform_html(
            "toutiao",
            "标题",
            "## 小节\n\n> 引用\n\n```text\nvless://【UUID】@【你的服务器IP】:443#【备注】\n```\n\n![图](../assets/a.png)",
            image_mode="placeholder",
        )

        self.assertIn("<title>标题 - 今日头条正文粘贴版</title>", rendered)
        self.assertNotIn("<article", rendered)
        self.assertNotIn("<h2 style=", rendered)
        self.assertNotIn("<section", rendered)
        self.assertIn("<h2>小节</h2>", rendered)
        self.assertIn("<blockquote><p>引用</p></blockquote>", rendered)
        self.assertIn("<pre", rendered)
        self.assertIn("<code", rendered)
        self.assertIn("【UUID】", rendered)
        self.assertIn("【服务器IP】", rendered)
        self.assertIn("图片占位 1", rendered)
        self.assertIn("../assets/a.png", rendered)
        self.assertNotIn("data:image/", rendered)
        self.assertNotIn("先说价值", rendered)
        self.assertNotIn("先说结论", rendered)
        self.assertNotIn("阅读方式", rendered)
        self.assertNotIn("本文路线", rendered)

    def test_render_zsxq_html_can_embed_local_images_as_data_uri(self):
        # Zsxq's editor does not preserve the WeChat magazine wrapper well.
        # Keep this output body-only and low-style so pasted long articles do
        # not inherit the WeChat background/card treatment.
        fixture_dir = Path(__file__).resolve().parent / "fixtures"
        rendered = build_publish_package.render_platform_html(
            "zsxq",
            "标题",
            "## 小节\n\n⚠️ 注意这件事。\n\n---\n\n| 问题 | 解决 |\n| --- | --- |\n| 连接失败 | 检查端口 |\n\n```text\nserver: 【你的服务器IP】\n```\n\n![本地图片](media/sample.png)",
            image_mode="data",
            asset_base_dir=fixture_dir,
        )

        self.assertNotIn("先说价值", rendered)
        self.assertNotIn("先说结论", rendered)
        self.assertNotIn("阅读方式", rendered)
        self.assertIn("<title>标题 - 知识星球</title>", rendered)
        self.assertIn("<body style=", rendered)
        self.assertIn('<h2 style="', rendered)
        self.assertIn(">小节</h2>", rendered)
        # Callout: bold label on its own line, body underneath (no inline ▍ bar).
        self.assertIn("<strong>⚠️ 注意</strong>", rendered)
        self.assertIn("注意这件事。", rendered)
        self.assertIn("<ul>", rendered)
        self.assertIn("连接失败", rendered)
        self.assertIn("检查端口", rendered)
        self.assertIn("<pre style=", rendered)
        self.assertIn("<code>", rendered)
        self.assertIn("【服务器IP】", rendered)
        self.assertIn('src="data:image/png;base64,', rendered)
        self.assertIn("max-width:100%;height:auto", rendered)
        self.assertIn("<img", rendered)
        self.assertNotIn("图片占位 1", rendered)
        self.assertNotIn("media/sample.png", rendered)
        self.assertNotIn("知识星球 粘贴版", rendered)
        self.assertNotIn("<article", rendered)
        self.assertNotIn("background:#f7f3ec", rendered)
        self.assertNotIn("border-left:3px solid #c2410c", rendered)
        self.assertNotIn("<table", rendered)

    def test_render_zsxq_ordered_steps_keep_numbering_across_images(self):
        # Zsxq uses plain paragraph numbering; keep numbering contiguous when
        # an image is embedded between repeated Markdown `1.` items.
        fixture_dir = Path(__file__).resolve().parent / "fixtures"
        rendered = build_publish_package.render_platform_html(
            "zsxq",
            "标题",
            "## 步骤\n\n1. 第一步\n![图](media/sample.png)\n\n1. 第二步\n1. 第三步\n![图](media/sample.png)\n\n1. 第四步",
            image_mode="data",
            asset_base_dir=fixture_dir,
        )

        self.assertIn("<strong>1.</strong>&nbsp;第一步</p>", rendered)
        self.assertIn("<strong>2.</strong>&nbsp;第二步</p>", rendered)
        self.assertIn("<strong>3.</strong>&nbsp;第三步</p>", rendered)
        self.assertIn("<strong>4.</strong>&nbsp;第四步</p>", rendered)
        self.assertIn('src="data:image/png;base64,', rendered)
        self.assertIn("max-width:100%;height:auto", rendered)
        self.assertNotIn("01.</span>", rendered)

    def test_render_zsxq_gcp_vless_does_not_inject_lead(self):
        rendered = build_publish_package.render_platform_html(
            "zsxq",
            "GCP VLESS",
            "今天使用 Google One 赠送的 GCP 余额搭建 VLESS Reality。\n\n## Step 1\n\n正文",
            image_mode="data",
        )

        self.assertIn("今天使用 Google One 赠送的 GCP 余额搭建 VLESS Reality。", rendered)
        self.assertIn(">Step 1</h2>", rendered)
        self.assertIn("<h2 style=", rendered)
        self.assertNotIn("先说结论", rendered)
        self.assertNotIn("不用域名、不用证书", rendered)
        self.assertNotIn("预算提醒", rendered)
        self.assertNotIn("先说价值", rendered)

    def test_render_zsxq_keeps_authored_paragraphs_without_overfit_promotion(self):
        # The old renderer promoted certain paragraphs to ▍ "visual quotes" based
        # on hardcoded phrases ("整个流程：", "不用时停止实例"…) overfit to one past
        # article. That logic is gone: authored paragraphs render as plain <p>,
        # and the ▍ bar is reserved for real `>` quotes only.
        rendered = build_publish_package.render_platform_html(
            "zsxq",
            "标题",
            "整个流程：**创建服务器 → 开端口 → 跑脚本 → 导入 Clash Verge → 连通**。\n\n"
            "**把这整段链接复制保存到本地**。这就是你的客户端配置，不要发到任何公开平台。\n\n"
            "不用时停止实例；确定不用了，删除 VM、磁盘、静态 IP 和项目，别留闲置资源。\n\n"
            "普通操作说明继续用正文。",
            image_mode="data",
        )

        self.assertIn("整个流程：", rendered)
        self.assertIn("把这整段链接复制保存到本地", rendered)
        self.assertIn("普通操作说明继续用正文。", rendered)
        # No keyword-based promotion to a ▍ quote marker.
        self.assertNotIn("▍", rendered)
        self.assertNotIn("color:#1a1a1a;font-weight:700", rendered)

    def test_render_zsxq_keeps_ai_article_out_of_wechat_magazine_layout(self):
        markdown = (
            "> 📖 > **导读**｜这一年，要说什么在悄悄改变我们每个人的工作方式，答案多半都指向 **AI**。\n\n"
            "## 01｜每个时代，都有一种「奇迹材料」\n\n"
            "文章一上来，就把视角拉得很高。\n\n"
            "---\n\n"
            "| **层面** | **旧世界（人力）** | **新世界（无限心智）** |\n"
            "| --- | --- | --- |\n"
            "| **个体** | 人当「胶水」 | 一个人同时指挥三四个 agent |\n"
        )

        rendered = build_publish_package.render_platform_html("zsxq", "AI", markdown, image_mode="data")

        self.assertIn("<title>AI - 知识星球</title>", rendered)
        self.assertIn("<strong>📖 导读</strong>", rendered)
        self.assertIn("｜这一年", rendered)
        self.assertNotIn("📖 &gt;", rendered)
        self.assertIn(">01｜每个时代，都有一种「奇迹材料」</h2>", rendered)
        self.assertIn(">文章一上来，就把视角拉得很高。</p>", rendered)
        self.assertIn("<ul><li><strong>个体</strong><br>", rendered)
        self.assertNotIn("<strong><strong>个体</strong></strong>", rendered)
        self.assertNotIn("<article", rendered)
        self.assertNotIn("background:#f7f3ec", rendered)
        self.assertNotIn("border-bottom:2px solid #fcd34d", rendered)

    def test_render_zsxq_uses_margins_instead_of_empty_spacer_paragraphs(self):
        rendered = build_publish_package.render_platform_html(
            "zsxq",
            "标题",
            "读完这篇，我脑子里挥之不去的，是 Ivan 那个最朴素、也最锋利的判断——\n\n"
            "**AI 不是一个功能，而是一种材料。**\n\n"
            "这二者的差别，很大。功能，是加在旧东西上的；材料，是用来重新造一个世界的。\n\n"
            "想透了这一层，我对 AI 的态度，就只剩两个字—— **All in。**",
            image_mode="data",
        )

        self.assertIn(">读完这篇，我脑子里挥之不去的，是 Ivan 那个最朴素、也最锋利的判断——</p>", rendered)
        self.assertIn("><strong>AI 不是一个功能，而是一种材料。</strong></p>", rendered)
        self.assertIn(">这二者的差别，很大。", rendered)
        self.assertIn("margin:0 0 1.05em;line-height:1.85", rendered)
        self.assertNotIn("<p><br></p>", rendered)

    def test_render_zsxq_quote_lab_contains_native_quote_experiments(self):
        rendered = build_publish_package.render_zsxq_quote_lab("标题")

        self.assertIn("知识星球原生引用实验", rendered)
        self.assertIn("<blockquote><p><strong>引用测试 A", rendered)
        self.assertIn("<blockquote><strong>引用测试 B", rendered)
        self.assertIn('data-type="blockquote"', rendered)
        self.assertIn('data-block="quote"', rendered)
        self.assertIn('role="blockquote"', rendered)
        self.assertIn("&gt; **引用测试 G", rendered)
        self.assertIn("▍引用测试 I", rendered)

    def test_render_toutiao_html_uses_body_only_paste_safe_markup(self):
        fixture_dir = Path(__file__).resolve().parent / "fixtures"
        rendered = build_publish_package.render_platform_html(
            "toutiao",
            "标题",
            "今天使用 Google One 赠送的 GCP 余额搭建 VLESS Reality。\n\n"
            "## 小节\n\n"
            "⚠️ 注意这件事。\n\n"
            "1. 第一步\n"
            "![图](media/sample.png)\n\n"
            "1. 第二步\n\n"
            "| **阈值** | **动作** |\n"
            "| --- | --- |\n"
            "| 50% | 邮件提醒 |\n"
            "| 100% | 邮件提醒 + 检查资源 |\n\n"
            "```text\nserver: 【你的服务器IP】\n```\n\n"
            "> 整个流程：创建服务器 → 开端口 → 导入 Clash Verge。",
            image_mode="data",
            asset_base_dir=fixture_dir,
        )

        self.assertIn("<title>标题 - 今日头条正文粘贴版</title>", rendered)
        self.assertIn("今天使用 Google One 赠送的 GCP 余额搭建 VLESS Reality。", rendered)
        self.assertNotIn("先说结论", rendered)
        self.assertNotIn("先说价值", rendered)
        self.assertNotIn("阅读方式", rendered)
        # Conservative native markup: Toutiao/SMZDM editors strip decorative CSS,
        # so headings are bare <h2>, emphasis is <strong>, and callouts are
        # native <blockquote> rather than a coloured magazine card.
        self.assertIn("<h2>小节</h2>", rendered)
        self.assertNotIn("<h2 style=", rendered)
        self.assertNotIn("background:#fdf6ec", rendered)
        self.assertNotIn("<section", rendered)
        self.assertIn("<blockquote>", rendered)
        self.assertIn("注意", rendered)
        self.assertIn("注意这件事", rendered)
        # Ordered list uses native <strong>N.</strong> leads (an <img> between the
        # two "1." items splits the list, so the second restarts at 2.).
        self.assertIn("<strong>1.</strong>", rendered)
        self.assertIn("第一步", rendered)
        self.assertIn("<strong>2.</strong>", rendered)
        self.assertIn("第二步", rendered)
        self.assertIn("50%", rendered)
        self.assertIn("邮件提醒 + 检查资源", rendered)
        self.assertIn("<pre", rendered)
        self.assertIn("【服务器IP】", rendered)
        self.assertIn('src="data:image/png;base64,', rendered)
        self.assertIn("整个流程", rendered)
        self.assertNotIn("▍", rendered)
        self.assertNotIn("今日头条 粘贴版", rendered)

    def test_platform_paragraph_split_does_not_break_bold_markup(self):
        markdown = (
            "这一段足够长，平台版会按句号拆分，避免单段在编辑器里太拥挤。"
            "而且卡帕西这次居然不是当高管，而是直接扎进技术团队干活。"
            " **冲着技术去的，不是冲着 title 去的。** 这说明他真的觉得 Anthropic 在技术路线上更有搞头。"
        )

        for platform in ("toutiao", "smzdm"):
            with self.subTest(platform=platform):
                rendered = build_publish_package.render_platform_html(platform, "标题", markdown)

                # Native renderer emits a single <strong> for the bold cluster —
                # the whole point of the native path is that emphasis is semantic
                # (survives style-stripping), not a styled <span>. We just need
                # the bold run intact: no leaked asterisks, no break across tags.
                self.assertIn(
                    "<strong>冲着技术去的，不是冲着 title 去的。</strong>", rendered
                )
                self.assertNotIn("**冲着技术", rendered)
                self.assertNotIn("** 这说明", rendered)

    def test_platform_guide_maps_recommended_files(self):
        guide = build_publish_package.render_platform_guide("标题")

        self.assertIn("platforms/zhihu.md", guide)
        self.assertIn("platforms/toutiao.html", guide)
        self.assertIn("platforms/zsxq.html", guide)
        self.assertIn("platforms/smzdm.html", guide)
        self.assertIn("--zhihu-asset-repo", guide)
        self.assertIn("md2zhihu", guide)
        self.assertIn("知识星球常见问题", guide)
        self.assertIn("什么值得买官方账号投稿指引", guide)

    def test_bold_label_and_colon_do_not_split_across_lines(self):
        rendered = build_publish_package.render_wechat_html("标题", "1. **核心** ：选择 Xray-core")
        segment = rendered.split("核心", 1)[0].rsplit("<p", 1)[-1] + "核心" + rendered.split("核心", 1)[1].split("</p>", 1)[0]

        # New editorial list numbers are zero-padded and live directly adjacent
        # to the item text (no &nbsp; spacer inside the number span itself).
        self.assertIn("01.</span>", rendered)
        # The bold label keeps the colon glued to "核心" so it cannot wrap onto
        # a new line and an &nbsp; separates the label cluster from the body.
        self.assertIn(
            '<span style="color:#1a1a1a;font-weight:700;">核心：</span>'
            '&nbsp;选择 Xray-core',
            rendered,
        )
        self.assertNotIn("<li", segment)
        self.assertNotIn("<ol", segment)
        self.assertNotIn("<strong", segment)
        self.assertNotIn("white-space:nowrap", segment)
        self.assertNotIn("&#8288;", segment)
        self.assertNotIn("</span> ：选择", segment)

    def test_bold_label_colon_uses_plain_nbsp_for_wechat_cleanup(self):
        rendered = build_publish_package.markdown_inline_to_html("**域名** ：不需要填")

        self.assertIn("域名：</span>&nbsp;不需要填", rendered)
        self.assertNotIn("&#8288;", rendered)
        self.assertNotIn("white-space:nowrap", rendered)
        self.assertNotIn("</span>：不需要填", rendered)

    def test_bold_label_colon_at_end_does_not_add_extra_nbsp(self):
        rendered = build_publish_package.markdown_inline_to_html("替换 **4 个占位符** ：")

        self.assertIn("4 个占位符：</span>", rendered)
        self.assertNotIn("4 个占位符：</span>&nbsp;", rendered)

    def test_editor_inline_keeps_bold_label_colon_together(self):
        rendered = build_publish_package.markdown_inline_to_editor_html("**GCP 服务器** ：你在云端的小电脑")

        self.assertIn("<strong>GCP 服务器：</strong>&nbsp;你在云端的小电脑", rendered)
        self.assertNotIn("</strong> ：", rendered)

    def test_extract_image_manifest_tracks_order_and_labels(self):
        manifest = build_publish_package.extract_image_manifest("![Image](assets/a.png)\n![表格](assets/table.png)")

        self.assertEqual(manifest[0]["index"], 1)
        self.assertEqual(manifest[0]["label"], "图片 1")
        self.assertEqual(manifest[1]["label"], "表格")

    def test_build_zhihu_markdown_falls_back_without_asset_repo(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "article.publish"
            (output / "platforms").mkdir(parents=True)
            relative, hosted, warnings = build_publish_package.build_zhihu_markdown(
                "标题",
                "## 小节\n\n![图](assets/a.png)\n",
                output,
                asset_repo=None,
            )

            self.assertEqual(relative, "platforms/zhihu.md")
            self.assertFalse(hosted)
            zhihu_md = (output / "platforms" / "zhihu.md").read_text(encoding="utf-8")
            # Fallback rewrites local asset links to ../assets/ so the Markdown
            # still points at real files relative to platforms/.
            self.assertIn("../assets/a.png", zhihu_md)
            self.assertTrue(any(item["code"] == "zhihu_asset_repo_missing" for item in warnings))
            # The temp md2zhihu source must not linger in the output dir.
            self.assertFalse((output / ".zhihu-src.md").exists())

    def test_build_zhihu_markdown_uses_converter_when_repo_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "article.publish"
            (output / "platforms").mkdir(parents=True)
            relative, hosted, warnings = build_publish_package.build_zhihu_markdown(
                "标题",
                "## 小节\n\n![图](assets/a.png)\n",
                output,
                asset_repo="git@github.com:u/bed.git@main",
                converter=fake_zhihu_convert,
            )

            self.assertEqual(relative, "platforms/zhihu.md")
            self.assertTrue(hosted)
            zhihu_md = (output / "platforms" / "zhihu.md").read_text(encoding="utf-8")
            self.assertIn("https://gitee.example.com/u/bed/raw/branch/a.png", zhihu_md)
            self.assertNotIn("](assets/a.png)", zhihu_md)
            self.assertEqual(warnings, [])
            self.assertFalse((output / ".zhihu-src.md").exists())

    def test_build_zhihu_markdown_warns_when_md2zhihu_missing(self):
        def missing_converter(*_args, **_kwargs):
            return zhihu_md2zhihu.ConvertResult(ok=False, error=zhihu_md2zhihu.INSTALL_HINT)

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "article.publish"
            (output / "platforms").mkdir(parents=True)
            relative, hosted, warnings = build_publish_package.build_zhihu_markdown(
                "标题",
                "正文\n",
                output,
                asset_repo="git@github.com:u/bed.git@main",
                converter=missing_converter,
            )

            self.assertEqual(relative, "platforms/zhihu.md")
            self.assertFalse(hosted)
            self.assertTrue((output / "platforms" / "zhihu.md").exists())
            self.assertTrue(any(item["code"] == "md2zhihu_not_installed" for item in warnings))

    def test_zhihu_md2zhihu_convert_reports_missing_binary(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = zhihu_md2zhihu.convert(
                Path(tmp) / "src.md",
                Path(tmp) / "out" / "zhihu.md",
                asset_repo="git@github.com:u/bed.git@main",
                md2zhihu_bin="md2zhihu-definitely-not-on-path",
            )

            self.assertFalse(result.ok)
            self.assertIsNotNone(result.error)

    def test_build_zhihu_markdown_handles_converter_exception(self):
        def bad_converter(*_args, **_kwargs):
            raise RuntimeError("some unexpected error")

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "article.publish"
            (output / "platforms").mkdir(parents=True)
            relative, hosted, warnings = build_publish_package.build_zhihu_markdown(
                "标题",
                "## 小节\n\n![图](assets/a.png)\n",
                output,
                asset_repo="git@github.com:u/bed.git@main",
                converter=bad_converter,
            )

            self.assertEqual(relative, "platforms/zhihu.md")
            self.assertFalse(hosted)
            self.assertTrue((output / "platforms" / "zhihu.md").exists())
            self.assertTrue(any(
                item["code"] == "zhihu_md2zhihu_failed" and "md2zhihu 调用异常：some unexpected error" in str(item["message"])
                for item in warnings
            ))

    def test_build_zhihu_markdown_warns_on_non_install_convert_error(self):
        def failed_converter(*_args, **_kwargs):
            return zhihu_md2zhihu.ConvertResult(ok=False, error="some runtime error from md2zhihu")

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "article.publish"
            (output / "platforms").mkdir(parents=True)
            relative, hosted, warnings = build_publish_package.build_zhihu_markdown(
                "标题",
                "## 小节\n\n![图](assets/a.png)\n",
                output,
                asset_repo="git@github.com:u/bed.git@main",
                converter=failed_converter,
            )

            self.assertEqual(relative, "platforms/zhihu.md")
            self.assertFalse(hosted)
            self.assertTrue((output / "platforms" / "zhihu.md").exists())
            self.assertTrue(any(
                item["code"] == "zhihu_md2zhihu_failed" and "some runtime error from md2zhihu" in str(item["message"])
                for item in warnings
            ))

    def test_build_package_creates_expected_outputs(self):
        fixture = Path(__file__).resolve().parent / "fixtures" / "article.md"
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "article.publish"
            result = build_publish_package.build_package(
                fixture,
                output,
                overwrite=False,
                strict=False,
                table_mode="never",
                style="magazine",
                download_remote_images=False,
            )

            self.assertEqual(result["title"], "多平台发布测试文章")

            # The slimmed-down output only ships the final paste-ready files.
            # Zhihu is now an import-ready Markdown (md2zhihu), not HTML.
            self.assertTrue((output / "wechat.html").exists())
            self.assertTrue((output / "platforms" / "zhihu.md").exists())
            self.assertFalse((output / "platforms" / "zhihu.html").exists())
            self.assertTrue((output / "platforms" / "toutiao.html").exists())
            # Zsxq ships a recommended Markdown file (native styling in the
            # editor's Markdown mode) plus the rich-text-mode HTML fallback.
            self.assertTrue((output / "platforms" / "zsxq.md").exists())
            self.assertTrue((output / "platforms" / "zsxq.html").exists())
            self.assertTrue((output / "platforms" / "smzdm.html").exists())
            # Xueqiu / Baijiahao: native rich-text HTML (like Toutiao).
            self.assertTrue((output / "platforms" / "xueqiu.html").exists())
            self.assertTrue((output / "platforms" / "baijiahao.html").exists())
            # Juejin: full Markdown (Vditor editor). Xiaohongshu: plain-text note.
            self.assertTrue((output / "platforms" / "juejin.md").exists())
            self.assertTrue((output / "platforms" / "xiaohongshu.md").exists())
            self.assertTrue((output / "report.json").exists())
            self.assertTrue((output / "assets" / "sample.png").exists())

            # Intermediate / diagnostic / fallback files are explicitly NOT shipped.
            for stale in [
                "wechat-placeholder.html",
                "wechat-preview.html",
                "wechat-embedded.html",
                "preview.html",
                "copy.html",
            ]:
                self.assertFalse((output / stale).exists(), f"{stale} should not be emitted")
            for stale in [
                "zhihu.html",
                "zhihu-embedded.html",
                "zhihu-remote.html",
                "zhihu-image-map.template.json",
                "toutiao.md",
                "smzdm.md",
                "platform-guide.md",
                "platform-report.json",
                "zsxq-quote-lab.html",
            ]:
                self.assertFalse(
                    (output / "platforms" / stale).exists(),
                    f"platforms/{stale} should not be emitted",
                )

            # The Zhihu local-link fallback still ships the manual upload order.
            self.assertTrue((output / "image-manifest.md").exists())

            report = json.loads((output / "report.json").read_text(encoding="utf-8"))
            self.assertEqual(report["tables"]["kept"], 1)
            self.assertIn("wechat.html", report["outputs"])
            self.assertIn("platforms/zhihu.md", report["outputs"])
            self.assertNotIn("platforms/zhihu.html", report["outputs"])
            self.assertIn("platforms/toutiao.html", report["outputs"])
            self.assertIn("platforms/zsxq.html", report["outputs"])
            self.assertIn("platforms/smzdm.html", report["outputs"])
            self.assertIn("image-manifest.md", report["outputs"])
            self.assertEqual(report["platforms"]["zhihu"]["recommended"], "platforms/zhihu.md")
            self.assertEqual(report["platforms"]["zhihu"]["html_image_mode"], "markdown-local")
            self.assertEqual(report["platforms"]["toutiao"]["html_image_mode"], "data")
            self.assertEqual(report["platforms"]["zsxq"]["html_image_mode"], "data")
            self.assertEqual(report["platforms"]["smzdm"]["html_image_mode"], "data")
            self.assertEqual(report["zhihu"]["engine"], "md2zhihu")
            self.assertFalse(report["zhihu"]["hosted"])
            self.assertIsNone(report["zhihu"]["asset_repo"])
            self.assertEqual(report["image_manifest"][0]["src"], "assets/sample.png")
            self.assertTrue(any(item["code"] == "zhihu_asset_repo_missing" for item in report["warnings"]))

            wechat_html = (output / "wechat.html").read_text(encoding="utf-8")
            self.assertIn("data:image/png;base64,", wechat_html)
            self.assertNotIn("图片占位 1", wechat_html)

            smzdm_html = (output / "platforms" / "smzdm.html").read_text(encoding="utf-8")
            self.assertIn("data:image/png;base64,", smzdm_html)
            self.assertNotIn("什么值得买 粘贴版", smzdm_html)
            self.assertNotIn("<h1", smzdm_html)
            self.assertNotIn("<header", smzdm_html)
            # SMZDM uses the conservative native renderer (no magazine <article>
            # wrapper, no <section> cards): native <h2> and <blockquote> instead.
            self.assertNotIn("<article", smzdm_html)
            self.assertNotIn("<section", smzdm_html)
            self.assertIn("<h2>", smzdm_html)
            self.assertIn("什么值得买正文粘贴版", smzdm_html)

            zhihu_md = (output / "platforms" / "zhihu.md").read_text(encoding="utf-8")
            # Without an asset repo, zhihu.md keeps local ../assets/ links and
            # never embeds Base64 images.
            self.assertIn("../assets/sample.png", zhihu_md)
            self.assertNotIn("data:image/png;base64,", zhihu_md)
            self.assertNotIn("先说价值", zhihu_md)
            self.assertNotIn("先说结论", zhihu_md)
            self.assertNotIn("阅读方式", zhihu_md)

            toutiao_html = (output / "platforms" / "toutiao.html").read_text(encoding="utf-8")
            self.assertIn("data:image/png;base64,", toutiao_html)

            zsxq_html = (output / "platforms" / "zsxq.html").read_text(encoding="utf-8")
            self.assertIn("data:image/png;base64,", zsxq_html)
            self.assertIn("<title>多平台发布测试文章 - 知识星球</title>", zsxq_html)
            self.assertIn("<body style=", zsxq_html)
            self.assertIn(">核心结论</h2>", zsxq_html)
            self.assertIn("<strong>▍</strong>&nbsp;好的发布包应该先保证结构稳定，再考虑自动发布。</p>", zsxq_html)
            self.assertIn("max-width:100%;height:auto", zsxq_html)
            self.assertNotIn("<p><br></p>", zsxq_html)
            self.assertNotIn("<article", zsxq_html)
            self.assertNotIn("知识星球长文粘贴版", zsxq_html)

            # Recommended Zsxq output is Markdown: quotes stay as `>` blockquotes
            # (so Zsxq's Markdown mode renders its native quote card), no `▍`
            # marker, no Base64, and images become greppable [[IMG_N]] text
            # placeholders (with the asset path) rather than broken local refs.
            zsxq_md = (output / "platforms" / "zsxq.md").read_text(encoding="utf-8")
            self.assertIn("> 好的发布包应该先保证结构稳定，再考虑自动发布。", zsxq_md)
            self.assertNotIn("▍", zsxq_md)
            self.assertNotIn("data:image/", zsxq_md)
            self.assertIn("[[IMG_1]]", zsxq_md)
            self.assertIn("assets/sample.png", zsxq_md)
            # The local image is now a placeholder, not a broken Markdown ref...
            self.assertNotIn("](assets/sample.png)", zsxq_md)
            # ...but a remote image URL stays a normal ref (it loads in-editor).
            self.assertIn("![远程图片](https://example.com/remote.png)", zsxq_md)

            # Xueqiu / Baijiahao share Toutiao's native renderer: native <h2>/
            # <strong>/<blockquote>, Base64 images, no magazine <section> cards.
            for plat, suffix in (("xueqiu", "雪球长文粘贴版"), ("baijiahao", "百家号正文粘贴版")):
                h = (output / "platforms" / f"{plat}.html").read_text(encoding="utf-8")
                self.assertIn(f"- {suffix}</title>", h)
                self.assertIn("<h2>", h)
                self.assertNotIn("<section", h)
                self.assertIn("data:image/png;base64,", h)

            # Juejin: full Markdown with [[IMG_N]] image placeholders.
            juejin_md = (output / "platforms" / "juejin.md").read_text(encoding="utf-8")
            self.assertIn("[[IMG_1]]", juejin_md)
            self.assertNotIn("](assets/sample.png)", juejin_md)
            self.assertNotIn("data:image/", juejin_md)

            # Xiaohongshu: plain-text note — no Markdown syntax, emoji kept, a
            # length hint, and image placeholders (uploaded manually in-app).
            xhs = (output / "platforms" / "xiaohongshu.md").read_text(encoding="utf-8")
            self.assertIn("小红书正文上限约 1000 字", xhs)
            self.assertNotIn("**", xhs)
            self.assertNotIn("](assets/", xhs)
            self.assertIn("[[IMG_1]]", xhs)

            self.assertTrue(any(item["code"] == "remote_image" for item in report["warnings"]))

    def test_build_package_hosts_zhihu_images_via_md2zhihu(self):
        fixture = Path(__file__).resolve().parent / "fixtures" / "article.md"
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "article.publish"

            report = build_publish_package.build_package(
                fixture,
                output,
                overwrite=False,
                strict=False,
                table_mode="never",
                style="magazine",
                download_remote_images=False,
                zhihu_asset_repo="git@github.com:u/bed.git@main",
                zhihu_converter=fake_zhihu_convert,
                open_after_build=False,
            )

            zhihu_md = (output / "platforms" / "zhihu.md").read_text(encoding="utf-8")

            self.assertIn("platforms/zhihu.md", report["outputs"])
            self.assertTrue(report["zhihu"]["hosted"])
            self.assertEqual(report["zhihu"]["asset_repo"], "git@github.com:u/bed.git@main")
            self.assertEqual(report["platforms"]["zhihu"]["html_image_mode"], "markdown")
            # md2zhihu rewrote the local image link to a git-hosted HTTPS URL.
            self.assertIn("https://gitee.example.com/u/bed/raw/branch/sample.png", zhihu_md)
            self.assertNotIn("../assets/sample.png", zhihu_md)
            self.assertNotIn("data:image/png;base64,", zhihu_md)
            self.assertFalse(
                any(item["code"] == "zhihu_asset_repo_missing" for item in report["warnings"])
            )

    def test_existing_output_without_overwrite_fails(self):
        fixture = Path(__file__).resolve().parent / "fixtures" / "article.md"
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "article.publish"
            output.mkdir()

            with self.assertRaises(FileExistsError):
                build_publish_package.build_package(
                    fixture,
                    output,
                    overwrite=False,
                    strict=False,
                    table_mode="never",
                    style="magazine",
                )

    def test_missing_local_image_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "article.md"
            source.write_text("# 标题\n\n![missing](./media/nope.png)\n", encoding="utf-8")

            with self.assertRaises(FileNotFoundError):
                build_publish_package.build_package(
                    source,
                    root / "out",
                    overwrite=False,
                    strict=False,
                    table_mode="never",
                    style="magazine",
                )

    def test_unsupported_style_fails(self):
        fixture = Path(__file__).resolve().parent / "fixtures" / "article.md"
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                build_publish_package.build_package(fixture, Path(tmp) / "out", style="technical", table_mode="never")

    def test_table_mode_never_keeps_table_count(self):
        fixture = Path(__file__).resolve().parent / "fixtures" / "article.md"
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "article.publish"
            result = build_publish_package.build_package(fixture, output, table_mode="never")

            self.assertEqual(result["tables"]["converted"], 0)
            self.assertEqual(result["tables"]["kept"], 1)

    def test_default_table_mode_reports_table_result(self):
        if shutil.which("uv") is None:
            self.skipTest("uv is required for table image conversion smoke test")
        fixture = Path(__file__).resolve().parent / "fixtures" / "article.md"
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "article.publish"
            result = build_publish_package.build_package(fixture, output, table_mode="auto")

            self.assertIn("converted", result["tables"])
            self.assertIn("kept", result["tables"])

    def test_normalize_cjk_punctuation_converts_only_chinese_context(self):
        n = build_publish_package.normalize_cjk_punctuation
        # Half-width punctuation inside Chinese prose becomes full-width.
        self.assertEqual(n("还稳不稳,别只盯"), "还稳不稳，别只盯")
        self.assertEqual(n("开篇:AI 涨成这样,还能看懂吗?"), "开篇：AI 涨成这样，还能看懂吗？")
        # Sees through emphasis markers + spaces: "...回报** :" -> full-width.
        self.assertEqual(n("有回报** :下面"), "有回报** ：下面")
        # Digit groups, inline code, and link targets are left untouched.
        self.assertEqual(n("约 3,800 亿"), "约 3,800 亿")
        self.assertEqual(n("`a,b:c` 普通,文本"), "`a,b:c` 普通，文本")
        self.assertEqual(
            n("见 [榜单](https://x.ai/r?a=1,b=2),很直观"),
            "见 [榜单](https://x.ai/r?a=1,b=2)，很直观",
        )
        # Pure ASCII context stays half-width.
        self.assertEqual(n("GPT-4,Claude: hi"), "GPT-4,Claude: hi")

    def test_punct_normalization_default_on_and_can_be_disabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "a.md"
            src.write_text("# 标题\n\n还稳不稳,别只盯股价\n", encoding="utf-8")

            on = Path(tmp) / "on.publish"
            build_publish_package.build_package(src, on, table_mode="never")
            on_html = (on / "wechat.html").read_text(encoding="utf-8")
            self.assertIn("稳不稳，别", on_html)

            off = Path(tmp) / "off.publish"
            build_publish_package.build_package(
                src, off, table_mode="never", normalize_punctuation=False
            )
            off_html = (off / "wechat.html").read_text(encoding="utf-8")
            self.assertIn("稳不稳,别", off_html)

    def test_cli_smoke_writes_report_json(self):
        fixture = Path(__file__).resolve().parent / "fixtures" / "article.md"
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "article.publish"
            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = build_publish_package.main([str(fixture), "--output", str(output), "--table-mode", "never"])

            self.assertEqual(exit_code, 0)
            self.assertTrue((output / "report.json").exists())
            self.assertEqual(json.loads(stdout.getvalue())["title"], "多平台发布测试文章")


if __name__ == "__main__":
    unittest.main()
