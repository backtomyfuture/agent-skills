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


if __name__ == "__main__":
    unittest.main()
