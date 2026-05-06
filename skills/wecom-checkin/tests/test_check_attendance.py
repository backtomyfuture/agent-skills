import importlib.util
import unittest
from datetime import datetime
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "check_attendance.py"
SPEC = importlib.util.spec_from_file_location("check_attendance", MODULE_PATH)
check_attendance = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(check_attendance)


class WorkdayCheckTests(unittest.TestCase):
    def test_normal_weekday_is_workday_by_chinese_calendar(self):
        status = check_attendance.workday_status(datetime(2026, 5, 6))

        self.assertTrue(status["is_workday"])
        self.assertEqual(status["source"], "chinese_calendar")
        self.assertIn("周三", status["reason"])

    def test_statutory_holiday_is_non_workday(self):
        status = check_attendance.workday_status(datetime(2026, 5, 1))

        self.assertFalse(status["is_workday"])
        self.assertTrue(status["is_holiday"])
        self.assertEqual(status["source"], "chinese_calendar")
        self.assertEqual(status["holiday_name"], "劳动节")

    def test_adjusted_weekend_can_be_workday(self):
        status = check_attendance.workday_status(datetime(2026, 5, 9))

        self.assertTrue(status["is_workday"])
        self.assertFalse(status["is_holiday"])
        self.assertEqual(status["source"], "chinese_calendar")
        self.assertIn("调休工作日", status["reason"])
        self.assertEqual(status["holiday_name"], "劳动节")

    def test_non_workday_result_skips_attendance_query(self):
        status = check_attendance.workday_status(datetime(2026, 5, 1))
        result = check_attendance.build_non_workday_result(datetime(2026, 5, 1), status)

        self.assertTrue(result["skipped"])
        self.assertEqual(result["query_start"], "2026-05-01")
        self.assertEqual(result["query_end"], "2026-05-01")
        self.assertEqual(result["total_records"], 0)
        self.assertFalse(result["workday"]["is_workday"])
        self.assertIn("无需检查打卡", result["summary"][0])


if __name__ == "__main__":
    unittest.main()
