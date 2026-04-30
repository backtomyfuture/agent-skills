import sys
import unittest
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import prepare_image  # noqa: E402


class PrepareImageTests(unittest.TestCase):
    def test_windows_large_base64_should_compress_for_command_line(self):
        self.assertTrue(
            prepare_image.should_compress_for_command_line(
                base64_chars=1_014_504,
                platform_name="nt",
                max_inline_chars=60_000,
            )
        )

    def test_non_windows_small_base64_does_not_need_command_line_compression(self):
        self.assertFalse(
            prepare_image.should_compress_for_command_line(
                base64_chars=29_004,
                platform_name="posix",
                max_inline_chars=60_000,
            )
        )


if __name__ == "__main__":
    unittest.main()
