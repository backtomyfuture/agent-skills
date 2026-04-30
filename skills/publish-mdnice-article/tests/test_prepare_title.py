import sys
import unittest
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import prepare_title  # noqa: E402


class PrepareTitleTests(unittest.TestCase):
    def test_generated_js_prefers_article_title_placeholder(self):
        js = prepare_title.generate_js("标题")

        self.assertIn("placeholder === '请输入标题'", js)
        self.assertIn("文章标题", js)


if __name__ == "__main__":
    unittest.main()
