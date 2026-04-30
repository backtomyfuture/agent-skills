import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import prepare_content  # noqa: E402


class PrepareContentTests(unittest.TestCase):
    def test_extract_title_ignores_utf8_bom(self):
        title, body = prepare_content.extract_title_and_body("\ufeff# 中文标题\n\n正文")

        self.assertEqual(title, "中文标题")
        self.assertEqual(body, "正文")

    def test_angle_wrapped_local_image_path_resolves(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            media = root / "article_media"
            media.mkdir()
            image_path = media / "image.png"
            image_path.write_bytes(b"fake")

            content = "before\n![](<./article_media/image.png>)\nafter"
            cleaned, images = prepare_content.strip_image_references(content, str(root))

            self.assertEqual(cleaned, "before\n[[IMG_1]]\nafter")
            self.assertEqual(images[0]["src"], "./article_media/image.png")
            self.assertEqual(Path(images[0]["resolved_path"]), image_path.resolve())


if __name__ == "__main__":
    unittest.main()
