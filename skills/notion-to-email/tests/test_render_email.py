import importlib.util
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "render_email.py"
SPEC = importlib.util.spec_from_file_location("render_email", MODULE_PATH)
render_email = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(render_email)


class RenderEmailTests(unittest.TestCase):
    def test_render_named_dash_entries_as_cards(self):
        block = {
            "type": "paragraph",
            "text": (
                '——"天机"预测模型：可吞吐海量历史销售数据。\n'
                '——"天策"航空求解器：针对雷雨导致的大面积延误。'
            ),
        }

        html = render_email.render_block(block)

        self.assertIn("天机预测模型", html)
        self.assertIn("天策航空求解器", html)
        self.assertIn("可吞吐海量历史销售数据。", html)
        self.assertIn("针对雷雨导致的大面积延误。", html)
        self.assertIn("border:1px solid", html)
        self.assertNotIn("&#9656;", html)

    def test_render_named_dash_entries_as_cards_when_preceded_by_intro_line(self):
        content = (
            "**南方航空：发布系列垂直领域AI大模型**\n"
            "南航在广州正式发布了多款航空专用AI大模型：\n"
            '——"天机"预测模型：可吞吐海量历史销售数据。\n'
            '——"天策"航空求解器：针对雷雨导致的大面积延误。'
        )

        blocks = render_email.parse_content(content)
        html = "\n".join(render_email.render_block(block) for block in blocks)

        self.assertIn("南航在广州正式发布了多款航空专用AI大模型：", html)
        self.assertIn("天机预测模型", html)
        self.assertIn("天策航空求解器", html)
        self.assertIn("border:1px solid", html)
        self.assertNotIn("&#9656;", html)


    def test_render_markdown_pipe_table(self):
        content = (
            "| **板块** | **核心动态** | **关联度** |\n"
            "| --- | --- | --- |\n"
            "| 宏观政策 | 发布典型场景 | ⭐⭐⭐ |"
        )
        blocks = render_email.parse_content(content)
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0]["type"], "table")
        html = render_email.render_block(blocks[0])
        self.assertIn("<table", html)
        self.assertIn("宏观政策", html)
        self.assertIn("发布典型场景", html)
        self.assertIn("⭐⭐⭐", html)


    def test_render_notion_callout_and_empty_block(self):
        content = (
            '<callout icon="💡" color="gray_bg">\n'
            '\t**启发**\n'
            '\t行业已把 AI 从创新项目转为可披露的经营要素。\n'
            '</callout>\n'
            '<empty-block/>'
        )
        blocks = render_email.parse_content(content)
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0]["type"], "insight")
        self.assertIn("行业已把 AI 从创新项目转为可披露的经营要素。", blocks[0]["text"])
        html = render_email.render_block(blocks[0])
        self.assertIn("💡 启发", html)
        self.assertIn("行业已把 AI 从创新项目转为可披露的经营要素。", html)

    def test_format_address_header_keeps_angle_brackets_plain(self):
        encoded = render_email._format_address_header(
            "宗晓婷(Vicky) <xt_zong@tianjin-air.com>"
        )
        self.assertIn("<xt_zong@tianjin-air.com>", encoded)
        self.assertNotIn("PHh0X3pvbmdAdGlhbmppbi1haXIuY29tPg==", encoded)

    def test_outlook_greeting_is_left_aligned_simsun_with_indent(self):
        greeting = (
            "晓婷姐，下面为本周的AI周报最新版，呈阅。\n"
            "建议后续审批路径：信息部总经理\n"
            "\n"
            "各位领导：\n"
            "以下为2026年9月第2周全球及国内民航业数智化相关动态汇编，供参阅。"
        )
        html = render_email._outlook_greeting_html(greeting)
        self.assertIn("font-family:SimSun", html)
        self.assertIn("font-size:16pt", html)
        self.assertIn("line-height:24pt", html)
        self.assertIn("text-align:left", html)
        self.assertIn("text-indent:32pt", html)
        self.assertIn("各位领导：", html)
        self.assertNotIn("align=\"center\"", html)

    def test_contact_line_sits_outside_the_card(self):
        html = render_email.render_html(
            "信息技术部 · AI周报 | 2026年9月第2周·民航业数智化动态与我司战略启示",
            [],
            "",
            "2026年9月10日",
        )
        contact = "如有问题，请联系信息技术部傅强，谢谢。"
        self.assertIn(contact, html)
        footer_idx = html.find("天津航空信息技术部")
        contact_idx = html.find(contact)
        card_close_idx = html.rfind("</table>", footer_idx, contact_idx)
        self.assertGreater(contact_idx, footer_idx)
        self.assertGreater(card_close_idx, footer_idx)
        self.assertGreater(contact_idx, card_close_idx)
        self.assertIn("font-size:16pt", html[contact_idx - 200 : contact_idx])


class CreateExchangeDraftTests(unittest.TestCase):
    def test_eml_to_draft_payload_inlines_cid_and_strips_display_names(self):
        from email.mime.image import MIMEImage
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText

        import importlib.util

        helper_path = Path(__file__).resolve().parents[1] / "scripts" / "create_exchange_draft.py"
        spec = importlib.util.spec_from_file_location("create_exchange_draft", helper_path)
        helper = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(helper)

        msg = MIMEMultipart("related")
        msg["Subject"] = "信息技术部 · AI周报 | 测试"
        msg["To"] = render_email._format_address_header(
            "宗晓婷(Vicky) <xt_zong@tianjin-air.com>"
        )
        msg["Cc"] = render_email._format_address_header(
            "张阳阳(Maggie) <yy-zhang1@tianjin-air.com>"
        )
        html = '<html><body><img src="cid:logo" alt="天津航空"><p>晓婷姐</p></body></html>'
        msg.attach(MIMEText(html, "html", "utf-8"))
        img = MIMEImage(b"\x89PNG\r\n\x1a\n", _subtype="png")
        img.add_header("Content-ID", "<logo>")
        msg.attach(img)

        eml_path = Path("/tmp/notion-email-draft-test.eml")
        eml_path.write_bytes(msg.as_bytes())
        payload = helper.eml_to_draft_payload(eml_path)

        self.assertEqual(payload["to"], ["xt_zong@tianjin-air.com"])
        self.assertEqual(payload["cc"], ["yy-zhang1@tianjin-air.com"])
        self.assertIn("data:image/png;base64,", payload["html"])
        self.assertNotIn("cid:logo", payload["html"])
        self.assertIn("晓婷姐", payload["html"])


if __name__ == "__main__":
    unittest.main()
