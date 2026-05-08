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

    def test_render_wechat_html_contains_magazine_style(self):
        rendered = build_publish_package.render_wechat_html("标题", "## 小节\n\n> 引用")

        self.assertIn("background:#fffdf8", rendered)
        self.assertIn("<h1", rendered)
        self.assertIn("blockquote", rendered)
        self.assertIn("小节", rendered)

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
            )

            self.assertEqual(result["title"], "多平台发布测试文章")
            self.assertTrue((output / "wechat.html").exists())
            self.assertTrue((output / "preview.html").exists())
            self.assertTrue((output / "copy.html").exists())
            self.assertTrue((output / "platforms" / "zhihu.md").exists())
            self.assertTrue((output / "platforms" / "toutiao.md").exists())
            self.assertTrue((output / "platforms" / "zsxq.md").exists())
            self.assertTrue((output / "platforms" / "smzdm.md").exists())
            self.assertTrue((output / "assets" / "sample.png").exists())
            report = json.loads((output / "report.json").read_text(encoding="utf-8"))
            self.assertEqual(report["tables"]["kept"], 1)
            self.assertIn("wechat.html", report["outputs"])
            self.assertTrue(any(item["code"] == "remote_image" for item in report["warnings"]))

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
