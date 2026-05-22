import json
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
import extract_remote_image_map  # noqa: E402
import upload_mdnice_images  # noqa: E402
import upload_zhihu_images  # noqa: E402


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

    def test_render_wechat_html_has_no_auto_header(self):
        # The user authors the title in the WeChat editor's title field and any
        # intro paragraph in the source Markdown. The renderer must NOT inject
        # an H1, gradient header, reading-time line, or "本文路线" outline.
        rendered = build_publish_package.render_wechat_html("标题", "## 小节\n\n> 引用")

        self.assertNotIn("linear-gradient(135deg,#0f172a", rendered)
        self.assertNotIn("linear-gradient(90deg,#eef4ff", rendered)
        self.assertNotIn("本文路线", rendered)
        self.assertNotIn("<h1", rendered)
        # Authored content still renders.
        self.assertIn("blockquote", rendered)
        self.assertIn("小节", rendered)

    def test_render_wechat_html_body_does_not_force_mobile_overflow(self):
        rendered = build_publish_package.render_wechat_html("标题", "## 小节\n\n正文")

        self.assertIn("<body style=\"box-sizing:border-box;", rendered)
        self.assertIn("padding:18px 0", rendered)
        self.assertIn("width:calc(100% - 40px)", rendered)
        self.assertIn("overflow-x:hidden", rendered)
        self.assertNotIn("<body style=\"width:100%;", rendered)

    def test_render_wechat_html_uses_editorial_heading_and_quote_styles(self):
        rendered = build_publish_package.render_wechat_html(
            "标题",
            "## 一级小节\n\n### 操作步骤\n\n> 如果不幸封号也不用慌张，退款基本都能追回。\n\n💡 这是一条提示。",
        )

        for stale_green in [
            "#ecfdf5",
            "#10b981",
            "#047857",
            "#0f766e",
            "#064e3b",
            "#a7f3d0",
            "rgba(15,118,110",
        ]:
            self.assertNotIn(stale_green, rendered)
        self.assertIn("border-left:5px solid #d97706", rendered)
        self.assertIn("background:transparent", rendered)
        self.assertIn("background:#111827", rendered)
        self.assertIn("border-left:4px solid #f59e0b", rendered)
        self.assertIn("color:#ffffff", rendered)
        self.assertIn("background:#fff7ed", rendered)
        self.assertIn("border-left:4px solid #d97706", rendered)
        self.assertIn("color:#78350f", rendered)
        self.assertIn("box-shadow:0 8px 22px rgba(17,24,39,0.06)", rendered)
        self.assertIn("font-weight:500", rendered)
        self.assertIn("💡 提示", rendered)

    def test_image_caption_paragraph_is_rendered_as_pill(self):
        # Image captions written as "*▼ ...*" should not leak raw asterisks; they
        # should turn into a small centered pill so they read like a caption.
        rendered = build_publish_package.render_wechat_html("标题", "*▼ 更新 Codex 后的入口*")

        self.assertNotIn("*▼", rendered)
        self.assertIn(">▼<", rendered)
        self.assertIn("更新 Codex 后的入口", rendered)
        self.assertIn("border-radius:999px", rendered)
        self.assertIn("letter-spacing:0", rendered)

    def test_inline_italic_is_rendered_as_em(self):
        # Single-asterisk emphasis should render as <em> instead of staying as
        # literal asterisks in the output.
        rendered = build_publish_package.render_wechat_html("标题", "正文 *强调内容* 结束")

        self.assertIn("<em", rendered)
        self.assertIn(">强调内容</em>", rendered)
        self.assertNotIn("*强调内容*", rendered)

    def test_inline_bold_still_works_alongside_italic(self):
        # The italic regex must not accidentally swallow ** bold ** markers.
        rendered = build_publish_package.render_wechat_html("标题", "**重要** 和 *次要*")

        self.assertIn("font-weight:700;\">重要</span>", rendered)
        self.assertIn(">次要</em>", rendered)

    def test_render_wechat_html_handles_lists_dividers_and_callouts(self):
        rendered = build_publish_package.render_wechat_html(
            "标题",
            "第一段导语。\n\n- 准备账号\n- 准备信用卡\n\n---\n\n⚠️ 不要开启付费升级。",
        )

        self.assertIn("<ul", rendered)
        self.assertIn("<li", rendered)
        self.assertIn("准备账号", rendered)
        self.assertIn(">—</p>", rendered)
        self.assertIn("color:#d8c7ad", rendered)
        self.assertIn("letter-spacing:0", rendered)
        self.assertNotIn("· · ·", rendered)
        self.assertNotIn("letter-spacing:8px", rendered)
        self.assertNotIn("height:1px", rendered)
        self.assertNotIn("<hr", rendered)
        self.assertIn("注意", rendered)
        self.assertNotIn(">---<", rendered)
        self.assertNotIn("<p", rendered.split("准备账号", 1)[0].rsplit("<ul", 1)[-1])

    def test_render_wechat_html_keeps_ordered_lists_readable_around_images(self):
        rendered = build_publish_package.render_wechat_html(
            "标题",
            "## 步骤\n\n1. 第一步\n![图](assets/a.png)\n\n1. 第二步\n1. 第三步",
        )

        self.assertIn("1.</span>&nbsp;第一步", rendered)
        self.assertIn("2.</span>&nbsp;第二步", rendered)
        self.assertIn("3.</span>&nbsp;第三步", rendered)
        self.assertNotIn('start="2"', rendered)
        self.assertIn("第二步", rendered)
        self.assertIn("第三步", rendered)

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
        self.assertIn("border:1px solid #e5e7eb", rendered)
        self.assertIn("box-shadow:0 8px 24px rgba(17,24,39,0.06)", rendered)
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

        self.assertIn("background:#f6f8fa", rendered)
        self.assertIn("color:#1f2937", rendered)
        self.assertIn("display:block", rendered)
        self.assertIn("white-space:pre-wrap", rendered)
        self.assertIn("server: example", rendered)
        self.assertNotIn(">yaml<", rendered)
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

    def test_render_platform_html_uses_conservative_editor_markup(self):
        rendered = build_publish_package.render_platform_html(
            "zhihu",
            "标题",
            "## 小节\n\n> 引用\n\n```text\nvless://【UUID】@【你的服务器IP】:443#【备注】\n```\n\n![图](../assets/a.png)",
            image_mode="placeholder",
        )

        self.assertIn("<title>标题 - 知乎正文粘贴版</title>", rendered)
        self.assertIn("<h2>小节</h2>", rendered)
        self.assertIn("<blockquote><p>引用</p></blockquote>", rendered)
        self.assertIn("<pre><code>", rendered)
        self.assertIn("【UUID】", rendered)
        self.assertIn("【服务器IP】", rendered)
        self.assertIn("图片占位 1", rendered)
        self.assertIn("../assets/a.png", rendered)
        self.assertNotIn("data:image/", rendered)
        self.assertNotIn("先说价值", rendered)
        self.assertNotIn("先说结论", rendered)
        self.assertNotIn("阅读方式", rendered)
        self.assertNotIn("知乎 粘贴版", rendered)
        self.assertNotIn("data-placeholder", rendered)
        self.assertNotIn("本文路线", rendered)
        self.assertNotIn("<p><br></p>", rendered)
        self.assertNotIn("<article", rendered)
        self.assertNotIn("style=", rendered)
        self.assertNotIn("<table", rendered)
        self.assertNotIn("<hr", rendered)

    def test_render_zsxq_html_can_embed_local_images_as_data_uri(self):
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
        self.assertIn("<p><br></p>", rendered)
        self.assertIn("<h2>小节</h2>", rendered)
        self.assertIn("<strong>▍⚠️ 注意：</strong>注意这件事。", rendered)
        self.assertIn("<ul><li><strong>连接失败</strong><br><strong>解决：</strong>检查端口</li></ul>", rendered)
        self.assertIn("<pre><code>", rendered)
        self.assertIn("【服务器IP】", rendered)
        self.assertIn('src="data:image/png;base64,', rendered)
        self.assertIn("<img", rendered)
        self.assertNotIn("图片占位 1", rendered)
        self.assertNotIn("media/sample.png", rendered)
        self.assertNotIn("知识星球 粘贴版", rendered)
        self.assertNotIn("style=", rendered)
        self.assertNotIn("<table", rendered)
        self.assertNotIn("<hr", rendered)
        self.assertNotIn("<article", rendered)

    def test_render_zsxq_budget_table_as_compact_action_list(self):
        rendered = build_publish_package.render_platform_html(
            "zsxq",
            "标题",
            "| **阈值** | **动作** |\n| --- | --- |\n| 50% | 邮件提醒 |\n| 90% | 邮件提醒 |\n| 100% | 邮件提醒 + 检查资源 |",
            image_mode="data",
        )

        self.assertIn("<li><strong>50%</strong>：邮件提醒</li>", rendered)
        self.assertIn("<li><strong>90%</strong>：邮件提醒</li>", rendered)
        self.assertIn("<li><strong>100%</strong>：邮件提醒 + 检查资源</li>", rendered)
        self.assertNotIn("<strong><strong>动作</strong>：</strong>", rendered)
        self.assertNotIn("动作：</strong>邮件提醒", rendered)
        self.assertNotIn("<table", rendered)

    def test_render_zsxq_ordered_steps_keep_numbering_across_images(self):
        fixture_dir = Path(__file__).resolve().parent / "fixtures"
        rendered = build_publish_package.render_platform_html(
            "zsxq",
            "标题",
            "## 步骤\n\n1. 第一步\n![图](media/sample.png)\n\n1. 第二步\n1. 第三步\n![图](media/sample.png)\n\n1. 第四步",
            image_mode="data",
            asset_base_dir=fixture_dir,
        )

        self.assertIn("<p><strong>1.</strong>&nbsp;第一步</p>", rendered)
        self.assertIn("<p><strong>2.</strong>&nbsp;第二步</p>", rendered)
        self.assertIn("<p><strong>3.</strong>&nbsp;第三步</p>", rendered)
        self.assertIn("<p><strong>4.</strong>&nbsp;第四步</p>", rendered)
        self.assertNotIn("<ol>", rendered)
        self.assertIn('src="data:image/png;base64,', rendered)

    def test_render_zsxq_gcp_vless_does_not_inject_lead(self):
        rendered = build_publish_package.render_platform_html(
            "zsxq",
            "GCP VLESS",
            "今天使用 Google One 赠送的 GCP 余额搭建 VLESS Reality。\n\n## Step 1\n\n正文",
            image_mode="data",
        )

        self.assertIn("今天使用 Google One 赠送的 GCP 余额搭建 VLESS Reality。", rendered)
        self.assertIn("<h2>Step 1</h2>", rendered)
        self.assertNotIn("先说结论", rendered)
        self.assertNotIn("不用域名、不用证书", rendered)
        self.assertNotIn("预算提醒", rendered)
        self.assertNotIn("先说价值", rendered)

    def test_render_zsxq_promotes_high_value_paragraphs_to_visual_quotes(self):
        rendered = build_publish_package.render_platform_html(
            "zsxq",
            "标题",
            "整个流程：**创建服务器 → 开端口 → 跑脚本 → 导入 Clash Verge → 连通**。\n\n"
            "**把这整段链接复制保存到本地**。这就是你的客户端配置，不要发到任何公开平台。\n\n"
            "Clash Verge Rev **不支持直接导入** `vless://` **链接**，需要手动新建一个本地 YAML 配置文件。\n\n"
            "不用时停止实例；确定不用了，删除 VM、磁盘、静态 IP 和项目，别留闲置资源。\n\n"
            "普通操作说明继续用正文。",
            image_mode="data",
        )

        self.assertIn("<p><strong>▍</strong>&nbsp;整个流程：<strong>创建服务器 → 开端口 → 跑脚本 → 导入 Clash Verge → 连通</strong>。</p>", rendered)
        self.assertIn("<p><strong>▍</strong>&nbsp;<strong>把这整段链接复制保存到本地</strong>。这就是你的客户端配置，不要发到任何公开平台。</p>", rendered)
        self.assertIn("<p><strong>▍</strong>&nbsp;Clash Verge Rev <strong>不支持直接导入</strong> <code>vless://</code> <strong>链接</strong>，需要手动新建一个本地 YAML 配置文件。</p>", rendered)
        self.assertIn("<p><strong>▍</strong>&nbsp;不用时停止实例；确定不用了，删除 VM、磁盘、静态 IP 和项目，别留闲置资源。</p>", rendered)
        self.assertNotIn("<blockquote>", rendered)
        self.assertIn("<p>普通操作说明继续用正文。</p>", rendered)

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
        self.assertIn("<h2>小节</h2>", rendered)
        self.assertIn("<blockquote><p><strong>⚠️ 注意：</strong>注意这件事。</p></blockquote>", rendered)
        self.assertIn("<p><strong>1.</strong>&nbsp;第一步</p>", rendered)
        self.assertIn("<p><strong>2.</strong>&nbsp;第二步</p>", rendered)
        self.assertIn("<li><strong>50%</strong>：邮件提醒</li>", rendered)
        self.assertIn("<li><strong>100%</strong>：邮件提醒 + 检查资源</li>", rendered)
        self.assertIn("<pre><code>", rendered)
        self.assertIn("【服务器IP】", rendered)
        self.assertIn('src="data:image/png;base64,', rendered)
        self.assertIn("<blockquote><p>整个流程", rendered)
        self.assertNotIn("<p><br></p>", rendered)
        self.assertNotIn("▍", rendered)
        self.assertNotIn("今日头条 粘贴版", rendered)
        self.assertNotIn("<article", rendered)
        self.assertNotIn("style=", rendered)
        self.assertNotIn("<table", rendered)
        self.assertNotIn("<hr", rendered)
        self.assertNotIn("<ol>", rendered)

    def test_platform_paragraph_split_does_not_break_bold_markup(self):
        markdown = (
            "这一段足够长，平台版会按句号拆分，避免单段在编辑器里太拥挤。"
            "而且卡帕西这次居然不是当高管，而是直接扎进技术团队干活。"
            " **冲着技术去的，不是冲着 title 去的。** 这说明他真的觉得 Anthropic 在技术路线上更有搞头。"
        )

        for platform in ("zhihu", "toutiao"):
            with self.subTest(platform=platform):
                rendered = build_publish_package.render_platform_html(platform, "标题", markdown)

                self.assertIn("<strong>冲着技术去的，不是冲着 title 去的。</strong>", rendered)
                self.assertNotIn("**冲着技术", rendered)
                self.assertNotIn("** 这说明", rendered)

    def test_platform_guide_maps_recommended_files(self):
        guide = build_publish_package.render_platform_guide("标题")

        self.assertIn("platforms/zhihu.html", guide)
        self.assertIn("platforms/toutiao.html", guide)
        self.assertIn("platforms/zsxq.html", guide)
        self.assertIn("platforms/smzdm.html", guide)
        self.assertIn("--zhihu-cookie-file", guide)
        self.assertIn("知识星球常见问题", guide)
        self.assertIn("什么值得买官方账号投稿指引", guide)

    def test_bold_label_and_colon_do_not_split_across_lines(self):
        rendered = build_publish_package.render_wechat_html("标题", "1. **核心** ：选择 Xray-core")
        segment = rendered.split("核心", 1)[0].rsplit("<p", 1)[-1] + "核心" + rendered.split("核心", 1)[1].split("</p>", 1)[0]

        self.assertIn("1.</span>&nbsp;", rendered)
        self.assertIn('<span style="color:#1a1a1a;font-weight:700;">核心：</span>&nbsp;选择 Xray-core', rendered)
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

    def test_rewrite_images_to_remote_urls_uses_https_map(self):
        rewritten, missing = build_publish_package.rewrite_images_to_remote_urls(
            "![图](../assets/a.png)\n![远程](https://example.com/already.png)",
            {"assets/a.png": "https://files.mdnice.com/user/1/a.png"},
        )

        self.assertIn("https://files.mdnice.com/user/1/a.png", rewritten)
        self.assertIn("https://example.com/already.png", rewritten)
        self.assertEqual(missing, [])

    def test_remote_image_map_extractor_pairs_urls_by_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            template = root / "template.json"
            source = root / "mdnice.html"
            output = root / "map.json"
            template.write_text(json.dumps({"../assets/a.png": "", "../assets/b.png": ""}), encoding="utf-8")
            source.write_text(
                '<figure><img src="https://files.mdnice.com/user/1/a.png"></figure>\n'
                '<figure><img src="https://files.mdnice.com/user/1/b.jpg"></figure>',
                encoding="utf-8",
            )

            code = extract_remote_image_map.main(["--template", str(template), "--source", str(source), "--output", str(output)])
            data = json.loads(output.read_text(encoding="utf-8"))

            self.assertEqual(code, 0)
            self.assertEqual(data["../assets/a.png"], "https://files.mdnice.com/user/1/a.png")
            self.assertEqual(data["../assets/b.png"], "https://files.mdnice.com/user/1/b.jpg")

    def test_upload_mdnice_images_builds_map_without_printing_token(self):
        original_upload = upload_mdnice_images.upload_mdnice
        try:
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                assets = root / "assets"
                platforms = root / "platforms"
                assets.mkdir()
                platforms.mkdir()
                image = assets / "a.png"
                image.write_bytes(b"png")
                template = platforms / "zhihu-image-map.template.json"
                output = platforms / "zhihu-image-map.json"
                template.write_text(json.dumps({"../assets/a.png": ""}), encoding="utf-8")

                def fake_upload(path, token, origin, endpoint=upload_mdnice_images.MDNICE_UPLOAD_URL):
                    self.assertEqual(token, "Bearer secret-token")
                    self.assertEqual(path.resolve(), image.resolve())
                    return "https://files.mdnice.com/user/1/a.png"

                upload_mdnice_images.upload_mdnice = fake_upload
                code = upload_mdnice_images.main(
                    [
                        "--template",
                        str(template),
                        "--output",
                        str(output),
                        "--token",
                        "secret-token",
                    ]
                )
                data = json.loads(output.read_text(encoding="utf-8"))

                self.assertEqual(code, 0)
                self.assertEqual(data["../assets/a.png"], "https://files.mdnice.com/user/1/a.png")
        finally:
            upload_mdnice_images.upload_mdnice = original_upload

    def test_upload_zhihu_images_builds_map_from_cookie_file(self):
        original_upload = upload_zhihu_images.upload_zhihu_image
        try:
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                assets = root / "assets"
                platforms = root / "platforms"
                assets.mkdir()
                platforms.mkdir()
                image = assets / "a.png"
                image.write_bytes(b"png")
                template = platforms / "zhihu-image-map.template.json"
                output = platforms / "zhihu-image-map.json"
                cookie_file = root / "cookies.json"
                template.write_text(json.dumps({"../assets/a.png": ""}), encoding="utf-8")
                cookie_file.write_text(
                    json.dumps({"z_c0": "auth", "_xsrf": "csrf", "d_c0": "device"}),
                    encoding="utf-8",
                )

                def fake_upload(opener, headers, file_path, source):
                    self.assertEqual(headers["x-xsrftoken"], "csrf")
                    self.assertEqual(file_path.resolve(), image.resolve())
                    self.assertEqual(source, "article")
                    return "https://picx.zhimg.com/v2-test.png"

                upload_zhihu_images.upload_zhihu_image = fake_upload
                code = upload_zhihu_images.main(
                    [
                        "--template",
                        str(template),
                        "--output",
                        str(output),
                        "--cookie-file",
                        str(cookie_file),
                    ]
                )
                data = json.loads(output.read_text(encoding="utf-8"))

                self.assertEqual(code, 0)
                self.assertEqual(data["../assets/a.png"], "https://picx.zhimg.com/v2-test.png")
        finally:
            upload_zhihu_images.upload_zhihu_image = original_upload

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
                zhihu_auto_upload=False,
            )

            self.assertEqual(result["title"], "多平台发布测试文章")

            # The slimmed-down output only ships the final paste-ready files.
            self.assertTrue((output / "wechat.html").exists())
            self.assertTrue((output / "platforms" / "zhihu.html").exists())
            self.assertTrue((output / "platforms" / "toutiao.html").exists())
            self.assertTrue((output / "platforms" / "zsxq.html").exists())
            self.assertTrue((output / "platforms" / "smzdm.html").exists())
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
                "zhihu.md",
                "zhihu-embedded.html",
                "zhihu-remote.html",
                "zhihu-image-map.template.json",
                "toutiao.md",
                "zsxq.md",
                "smzdm.md",
                "platform-guide.md",
                "platform-report.json",
                "zsxq-quote-lab.html",
            ]:
                self.assertFalse(
                    (output / "platforms" / stale).exists(),
                    f"platforms/{stale} should not be emitted",
                )

            # Zhihu needs uploaded HTTPS images. Without cookies or a remote
            # image map, zhihu.html must use explicit placeholders, while the
            # manifest ships the manual replacement order.
            self.assertTrue((output / "image-manifest.md").exists())

            report = json.loads((output / "report.json").read_text(encoding="utf-8"))
            self.assertEqual(report["tables"]["kept"], 1)
            self.assertIn("wechat.html", report["outputs"])
            self.assertIn("platforms/zhihu.html", report["outputs"])
            self.assertIn("platforms/toutiao.html", report["outputs"])
            self.assertIn("platforms/zsxq.html", report["outputs"])
            self.assertIn("platforms/smzdm.html", report["outputs"])
            self.assertIn("image-manifest.md", report["outputs"])
            self.assertNotIn("platforms/zhihu-embedded.html", report["outputs"])
            self.assertNotIn("platforms/zhihu-image-map.template.json", report["outputs"])
            self.assertEqual(report["platforms"]["zhihu"]["html_image_mode"], "placeholder")
            self.assertEqual(report["platforms"]["toutiao"]["html_image_mode"], "data")
            self.assertEqual(report["platforms"]["zsxq"]["html_image_mode"], "data")
            self.assertEqual(report["platforms"]["smzdm"]["html_image_mode"], "data")
            self.assertIsNone(report["remote_images"]["map"])
            self.assertEqual(report["image_manifest"][0]["src"], "assets/sample.png")
            self.assertTrue(any(item["code"] == "zhihu_image_upload_required" for item in report["warnings"]))

            wechat_html = (output / "wechat.html").read_text(encoding="utf-8")
            self.assertIn("data:image/png;base64,", wechat_html)
            self.assertNotIn("图片占位 1", wechat_html)

            smzdm_html = (output / "platforms" / "smzdm.html").read_text(encoding="utf-8")
            self.assertIn("data:image/png;base64,", smzdm_html)
            self.assertNotIn("什么值得买 粘贴版", smzdm_html)
            self.assertNotIn("<h1", smzdm_html)
            self.assertNotIn("<article", smzdm_html)
            self.assertNotIn("<header", smzdm_html)

            zhihu_html = (output / "platforms" / "zhihu.html").read_text(encoding="utf-8")
            # Zhihu's real editor rejects Base64 images, so no-cookie output is
            # intentionally a pasteable body with explicit image placeholders.
            self.assertIn("图片占位 1", zhihu_html)
            self.assertIn("../assets/sample.png", zhihu_html)
            self.assertNotIn("data:image/png;base64,", zhihu_html)
            self.assertNotIn("先说价值", zhihu_html)
            self.assertNotIn("先说结论", zhihu_html)
            self.assertNotIn("阅读方式", zhihu_html)

            toutiao_html = (output / "platforms" / "toutiao.html").read_text(encoding="utf-8")
            self.assertIn("data:image/png;base64,", toutiao_html)

            zsxq_html = (output / "platforms" / "zsxq.html").read_text(encoding="utf-8")
            self.assertIn("data:image/png;base64,", zsxq_html)
            self.assertIn("▍", zsxq_html)

            self.assertTrue(any(item["code"] == "remote_image" for item in report["warnings"]))

    def test_build_package_with_remote_image_map_creates_zhihu_remote_html(self):
        fixture = Path(__file__).resolve().parent / "fixtures" / "article.md"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / "article.publish"
            remote_map = root / "zhihu-image-map.json"
            remote_map.write_text(
                json.dumps({"../assets/sample.png": "https://files.mdnice.com/user/1/sample.png"}),
                encoding="utf-8",
            )

            report = build_publish_package.build_package(
                fixture,
                output,
                overwrite=False,
                strict=False,
                table_mode="never",
                style="magazine",
                remote_image_map=remote_map,
                zhihu_auto_upload=False,
            )
            # The slimmed-down design folds the remote-image variant into
            # zhihu.html itself; there is no separate zhihu-remote.html now.
            zhihu_html = (output / "platforms" / "zhihu.html").read_text(encoding="utf-8")

            self.assertIn("platforms/zhihu.html", report["outputs"])
            self.assertFalse((output / "platforms" / "zhihu-remote.html").exists())
            self.assertIn('src="https://files.mdnice.com/user/1/sample.png"', zhihu_html)
            self.assertIn('src="https://example.com/remote.png"', zhihu_html)
            self.assertNotIn("图片占位 1", zhihu_html)
            self.assertEqual(report["remote_images"]["zhihu_missing"], [])

    def test_build_package_auto_uploads_zhihu_images_when_available(self):
        fixture = Path(__file__).resolve().parent / "fixtures" / "article.md"
        original_try_upload = build_publish_package.try_upload_zhihu_images
        try:
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                output = root / "article.publish"
                cookie_file = root / "cookies.json"
                cookie_file.write_text("{}", encoding="utf-8")

                def fake_try_upload(image_manifest, asset_base_dir, cookie_file, verbose=True):
                    self.assertEqual(Path(cookie_file).name, "cookies.json")
                    self.assertTrue((asset_base_dir / "assets" / "sample.png").exists())
                    return (
                        {
                            "assets/sample.png": "https://picx.zhimg.com/v2-api-upload.png",
                            "../assets/sample.png": "https://picx.zhimg.com/v2-api-upload.png",
                        },
                        None,
                    )

                build_publish_package.try_upload_zhihu_images = fake_try_upload
                report = build_publish_package.build_package(
                    fixture,
                    output,
                    overwrite=False,
                    strict=False,
                    table_mode="never",
                    style="magazine",
                    zhihu_cookie_file=cookie_file,
                    open_after_build=False,
                )
                zhihu_html = (output / "platforms" / "zhihu.html").read_text(encoding="utf-8")

                self.assertEqual(report["platforms"]["zhihu"]["html_image_mode"], "remote")
                self.assertIn('src="https://picx.zhimg.com/v2-api-upload.png"', zhihu_html)
                self.assertIn('src="https://example.com/remote.png"', zhihu_html)
                self.assertNotIn("data:image/png;base64,", zhihu_html)
                self.assertNotIn("图片占位 1", zhihu_html)
                self.assertFalse(any(item["code"] == "zhihu_image_upload_required" for item in report["warnings"]))
        finally:
            build_publish_package.try_upload_zhihu_images = original_try_upload

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
