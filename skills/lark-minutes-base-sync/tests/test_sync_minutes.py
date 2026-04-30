import importlib.util
import contextlib
import io
import pathlib
import sys
import unittest


SCRIPT_PATH = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "sync_minutes.py"
spec = importlib.util.spec_from_file_location("sync_minutes", SCRIPT_PATH)
sync_minutes = importlib.util.module_from_spec(spec)
sys.modules["sync_minutes"] = sync_minutes
spec.loader.exec_module(sync_minutes)


class SyncMinutesTests(unittest.TestCase):
    def test_parse_search_item_extracts_metadata(self):
        item = {
            "display_info": (
                "顺鑫卡产品推广方案规划\n"
                "&lt;b&gt;关键词:&lt;/b&gt; 积分, 到期, 余额\n"
                "所有者: 傅强 开始时间: 2026.04.20 16:24:52 时长: 25 分 16 秒"
            ),
            "meta_data": {
                "description": "所有者: 傅强 开始时间: 2026.04.20 16:24:52 时长: 25 分 16 秒",
                "app_link": "https://a1qr0odzabr.feishu.cn/minutes/obcn5uxbbes5r6glhu5b69t1",
            },
            "token": "obcn5uxbbes5r6glhu5b69t1",
        }

        parsed = sync_minutes.parse_search_item(item)

        self.assertEqual(parsed.title, "顺鑫卡产品推广方案规划")
        self.assertEqual(parsed.owner_name, "傅强")
        self.assertEqual(parsed.start_time, "2026-04-20 16:24:52")
        self.assertEqual(parsed.duration_text, "25分16秒")
        self.assertEqual(parsed.token, "obcn5uxbbes5r6glhu5b69t1")

    def test_initial_state_does_not_backfill(self):
        now_ms = 1777449600000

        should_continue, next_state = sync_minutes.prepare_state(None, now_ms)

        self.assertFalse(should_continue)
        self.assertEqual(next_state["last_checked_at_ms"], now_ms)
        self.assertEqual(next_state["capture_started_at_ms"], now_ms)
        self.assertTrue(next_state["initialized"])

    def test_search_window_uses_overlap_without_crossing_capture_start(self):
        state = {
            "initialized": True,
            "capture_started_at_ms": 10000,
            "last_checked_at_ms": 11000,
        }

        start_ms, end_ms = sync_minutes.build_search_window(state, now_ms=20000, overlap_ms=5000)

        self.assertEqual(start_ms, 10000)
        self.assertEqual(end_ms, 20000)

    def test_build_record_payload_uses_minutes_token_field(self):
        minute = sync_minutes.MinuteRecord(
            token="obcn1",
            title="新录音",
            url="https://example.feishu.cn/minutes/obcn1",
            owner_name="傅强",
            owner_id="ou_owner",
            start_time="2026-04-28 17:41:02",
            duration_text="21秒",
            create_time_ms=1777369262063,
        )
        rich = sync_minutes.RichContent(
            summary="一句话摘要",
            todos="无",
            chapters="章节要点",
            transcript="完整转写",
            status="已捕获",
        )
        payload = sync_minutes.build_record_payload(minute, rich)

        self.assertEqual(payload["妙记Token"], "obcn1")
        self.assertEqual(payload["会议名称"], "新录音")
        self.assertEqual(payload["会议时长"], "21秒")
        self.assertEqual(payload["同步状态"], "已捕获")
        self.assertEqual(payload["AI总结"], "一句话摘要")
        self.assertEqual(payload["待办事项"], "无")
        self.assertEqual(payload["章节要点"], "章节要点")
        self.assertEqual(payload["转写内容"], "完整转写")
        self.assertNotIn("妙记链接", payload)
        self.assertNotIn("最后同步时间", payload)
        self.assertNotIn("关键词", payload)
        self.assertNotIn("来源关系", payload)

    def test_build_link_payload_uses_title_as_display_text(self):
        minute = sync_minutes.MinuteRecord(
            token="obcn1",
            title="新录音",
            url="https://example.feishu.cn/minutes/obcn1",
        )

        payload = sync_minutes.build_link_payload(minute)

        self.assertEqual(
            payload["妙记链接"],
            {"text": "新录音", "link": "https://example.feishu.cn/minutes/obcn1"},
        )

    def test_source_mode_defaults_to_manual(self):
        args = sync_minutes.build_parser().parse_args([])

        self.assertEqual(args.source_mode, "manual")

    def test_video_minute_tokens_for_day_collects_recording_tokens(self):
        calls = []
        original_run_lark = sync_minutes.run_lark

        def fake_run_lark(cmd, cwd=None):
            calls.append(cmd)
            if cmd[:2] == ["vc", "+search"]:
                return {"data": {"items": [{"id": "meeting_1"}, {"id": "meeting_2"}], "has_more": False}}
            if cmd[:2] == ["vc", "+recording"]:
                return {
                    "data": {
                        "recordings": [
                            {"meeting_id": "meeting_1", "minute_token": "obcn_auto"},
                            {"meeting_id": "meeting_2", "error": "failed to query recording"},
                        ]
                    }
                }
            raise AssertionError(f"unexpected command: {cmd}")

        try:
            sync_minutes.run_lark = fake_run_lark
            tokens = sync_minutes.video_minute_tokens_for_day("2026-04-20")
        finally:
            sync_minutes.run_lark = original_run_lark

        self.assertEqual(tokens, {"obcn_auto"})
        self.assertEqual(calls[0][:2], ["vc", "+search"])
        self.assertEqual(calls[1][:2], ["vc", "+recording"])
        self.assertIn("meeting_1,meeting_2", calls[1])

    def test_is_video_meeting_minute_uses_day_cache(self):
        calls = []
        original_video_tokens = sync_minutes.video_minute_tokens_for_day

        def fake_video_tokens(day):
            calls.append(day)
            return {"obcn_auto"}

        minute = sync_minutes.MinuteRecord(
            token="obcn_auto",
            title="信息部IT人员能力提升培训-Claud Code",
            url="https://example.feishu.cn/minutes/obcn_auto",
            start_time="2025-11-17 14:00:16",
        )
        cache = {}

        try:
            sync_minutes.video_minute_tokens_for_day = fake_video_tokens
            self.assertTrue(sync_minutes.is_video_meeting_minute(minute, cache))
            self.assertTrue(sync_minutes.is_video_meeting_minute(minute, cache))
        finally:
            sync_minutes.video_minute_tokens_for_day = original_video_tokens

        self.assertEqual(calls, ["2025-11-17"])

    def test_manual_source_classification_fails_without_minute_day(self):
        minute = sync_minutes.MinuteRecord(
            token="obcn_unknown_source",
            title="无法判定来源的新妙记",
            url="https://example.feishu.cn/minutes/obcn_unknown_source",
            start_time="",
        )

        with self.assertRaises(sync_minutes.SourceClassificationError):
            sync_minutes.is_video_meeting_minute(minute, {})

    def test_extract_rich_content_handles_artifacts_and_transcript_file(self):
        payload = {
            "data": {
                "artifacts": {
                    "summary": {"text": "摘要"},
                    "todos": [{"text": "跟进事项"}],
                    "chapters": [{"title": "第一章", "summary_content": "要点"}],
                    "transcript_file": "minutes/obcn1/transcript.txt",
                }
            }
        }

        rich = sync_minutes.extract_rich_content(payload, read_file=lambda path: f"read:{path}")

        self.assertEqual(rich.summary, "摘要")
        self.assertEqual(rich.todos, "跟进事项")
        self.assertIn("第一章", rich.chapters)
        self.assertIn("要点", rich.chapters)
        self.assertEqual(rich.transcript, "read:minutes/obcn1/transcript.txt")

    def test_runtime_has_no_subcommands(self):
        args = sync_minutes.build_parser().parse_args([])
        self.assertFalse(args.dry_run)
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                sync_minutes.build_parser().parse_args(["unsupported-command"])


if __name__ == "__main__":
    unittest.main()
