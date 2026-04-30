#!/usr/bin/env python3
"""Capture Fu Qiang owned Lark Minutes into a Feishu Base inbox."""

from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_BASE_TOKEN = "AArpb8s1daYUytsAxWgciWeVnud"
DEFAULT_TABLE_ID = "tbloqAEhgMnSXMi8"
DEFAULT_OWNER_IDS = "me"
DEFAULT_OWNER_NAME = "傅强"
DEFAULT_STATE_FILE = Path.home() / ".lark-minutes-base-sync" / "state.json"
DEFAULT_ARTIFACT_DIR = Path.home() / ".lark-minutes-base-sync" / "artifacts"
DEFAULT_OVERLAP_MINUTES = 10
TOKEN_FIELD = "妙记Token"
LINK_FIELD = "妙记链接"
SOURCE_MODE_MANUAL = "manual"
SOURCE_MODE_ALL = "all"


@dataclass
class MinuteRecord:
    token: str
    title: str
    url: str
    owner_name: str = ""
    owner_id: str = ""
    start_time: str = ""
    duration_text: str = ""
    create_time_ms: int = 0


@dataclass
class RichContent:
    summary: str = ""
    todos: str = "无"
    chapters: str = ""
    transcript: str = ""
    status: str = "已捕获"


class LarkCommandError(RuntimeError):
    def __init__(self, message: str, payload: dict[str, Any], returncode: int):
        super().__init__(message)
        self.payload = payload
        self.returncode = returncode


class SourceClassificationError(RuntimeError):
    """Raised when manual-mode filtering cannot safely classify a minute source."""


def run_lark(args: list[str], cwd: Path | None = None) -> dict[str, Any]:
    proc = subprocess.run(
        ["lark-cli", *args],
        cwd=str(cwd) if cwd else None,
        text=True,
        capture_output=True,
        check=False,
    )
    raw = proc.stdout.strip() or proc.stderr.strip()
    try:
        parsed = json.loads(raw) if raw else {}
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"lark-cli returned non-JSON output: {raw}") from exc
    if proc.returncode != 0 or parsed.get("ok") is False or parsed.get("code") not in (None, 0):
        message = parsed.get("error", {}).get("message") or parsed.get("msg") or raw
        raise LarkCommandError(message, parsed, proc.returncode)
    return parsed


def parse_search_item(item: dict[str, Any]) -> MinuteRecord:
    display = html.unescape(str(item.get("display_info") or ""))
    lines = [line.strip() for line in display.splitlines() if line.strip()]
    title = lines[0] if lines else str(item.get("token") or "")
    desc = str(item.get("meta_data", {}).get("description") or "")
    owner_name, start_time, duration_text = parse_description(desc)
    return MinuteRecord(
        token=str(item.get("token") or ""),
        title=title,
        url=str(item.get("meta_data", {}).get("app_link") or ""),
        owner_name=owner_name,
        start_time=start_time,
        duration_text=duration_text,
        create_time_ms=parse_local_time_ms(start_time),
    )


def parse_description(desc: str) -> tuple[str, str, str]:
    match = re.search(r"所有者:\s*(.*?)\s+开始时间:\s*([0-9.:\s-]+)\s+时长:\s*(.*)$", desc)
    if not match:
        return "", "", ""
    return match.group(1).strip(), match.group(2).strip().replace(".", "-"), normalize_duration(match.group(3).strip())


def normalize_duration(text: str) -> str:
    return re.sub(r"\s+", "", text)


def parse_local_time_ms(value: str) -> int:
    if not value:
        return 0
    try:
        parsed = dt.datetime.strptime(value, "%Y-%m-%d %H:%M:%S").astimezone()
    except ValueError:
        return 0
    return int(parsed.timestamp() * 1000)


def now_ms() -> int:
    return int(dt.datetime.now(dt.timezone.utc).timestamp() * 1000)


def lark_time(ts_ms: int) -> str:
    return dt.datetime.fromtimestamp(ts_ms / 1000).astimezone().isoformat(timespec="seconds")


def load_state(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def prepare_state(state: dict[str, Any] | None, current_ms: int) -> tuple[bool, dict[str, Any]]:
    if not state:
        return False, {
            "initialized": True,
            "capture_started_at_ms": current_ms,
            "last_checked_at_ms": current_ms,
        }
    state = dict(state)
    state.setdefault("initialized", True)
    state.setdefault("capture_started_at_ms", int(state.get("last_checked_at_ms") or current_ms))
    state.setdefault("last_checked_at_ms", current_ms)
    return True, state


def build_search_window(state: dict[str, Any], now_ms: int, overlap_ms: int) -> tuple[int, int]:
    capture_started = int(state.get("capture_started_at_ms") or state.get("last_checked_at_ms") or now_ms)
    last_checked = int(state.get("last_checked_at_ms") or capture_started)
    return max(capture_started, last_checked - overlap_ms), now_ms


def search_owned_minutes(owner_ids: str, start_ms: int, end_ms: int) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    page_token = ""
    while True:
        cmd = [
            "minutes",
            "+search",
            "--owner-ids",
            owner_ids,
            "--start",
            lark_time(start_ms),
            "--end",
            lark_time(end_ms),
            "--page-size",
            "30",
            "--format",
            "json",
            "--as",
            "user",
        ]
        if page_token:
            cmd.extend(["--page-token", page_token])
        payload = run_lark(cmd)
        data = payload.get("data", {})
        items.extend(data.get("items") or [])
        page_token = str(data.get("page_token") or "")
        if not data.get("has_more") or not page_token:
            break
    by_token = {str(item.get("token")): item for item in items if item.get("token")}
    return list(by_token.values())


def minute_day(minute: MinuteRecord) -> str:
    if re.match(r"^\d{4}-\d{2}-\d{2}", minute.start_time):
        return minute.start_time[:10]
    return ""


def search_video_meetings_for_day(day: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    page_token = ""
    while True:
        cmd = [
            "vc",
            "+search",
            "--start",
            day,
            "--end",
            day,
            "--page-size",
            "30",
            "--format",
            "json",
            "--as",
            "user",
        ]
        if page_token:
            cmd.extend(["--page-token", page_token])
        payload = run_lark(cmd)
        data = payload.get("data", {})
        items.extend(data.get("items") or [])
        page_token = str(data.get("page_token") or "")
        if not data.get("has_more") or not page_token:
            break
    return items


def recording_minute_tokens(meeting_ids: list[str]) -> set[str]:
    tokens: set[str] = set()
    for index in range(0, len(meeting_ids), 20):
        batch = meeting_ids[index : index + 20]
        if not batch:
            continue
        payload = run_lark(
            [
                "vc",
                "+recording",
                "--meeting-ids",
                ",".join(batch),
                "--format",
                "json",
                "--as",
                "user",
            ]
        )
        for recording in payload.get("data", {}).get("recordings") or []:
            if isinstance(recording, dict) and recording.get("minute_token"):
                tokens.add(str(recording["minute_token"]))
    return tokens


def video_minute_tokens_for_day(day: str) -> set[str]:
    meeting_ids = [str(item.get("id")) for item in search_video_meetings_for_day(day) if item.get("id")]
    return recording_minute_tokens(meeting_ids)


def is_video_meeting_minute(minute: MinuteRecord, day_token_cache: dict[str, set[str]]) -> bool:
    day = minute_day(minute)
    if not day:
        raise SourceClassificationError(
            f"cannot determine source for minute token {minute.token}: missing or unparsable start time"
        )
    if day not in day_token_cache:
        day_token_cache[day] = video_minute_tokens_for_day(day)
    return minute.token in day_token_cache[day]


def token_exists(base_token: str, table_id: str, token: str) -> bool:
    payload = run_lark(
        [
            "base",
            "+record-search",
            "--base-token",
            base_token,
            "--table-id",
            table_id,
            "--json",
            json.dumps(
                {
                    "keyword": token,
                    "search_fields": [TOKEN_FIELD],
                    "select_fields": [TOKEN_FIELD],
                    "offset": 0,
                    "limit": 1,
                },
                ensure_ascii=False,
            ),
            "--as",
            "user",
        ]
    )
    return bool(payload.get("data", {}).get("record_id_list"))


def build_record_payload(minute: MinuteRecord, rich: RichContent | None = None) -> dict[str, Any]:
    rich = rich or RichContent()
    payload: dict[str, Any] = {
        TOKEN_FIELD: minute.token,
        "会议名称": minute.title,
        "组织者": minute.owner_name or DEFAULT_OWNER_NAME,
        "会议日期": minute.start_time,
        "会议时长": minute.duration_text,
        "AI总结": rich.summary,
        "待办事项": rich.todos,
        "章节要点": rich.chapters,
        "转写内容": rich.transcript,
        "同步状态": rich.status,
    }
    return {key: value for key, value in payload.items() if value not in ("", None, [])}


def build_link_payload(minute: MinuteRecord) -> dict[str, Any]:
    return {LINK_FIELD: {"text": minute.title or minute.url, "link": minute.url}}


def fetch_rich_content(token: str, artifact_dir: Path) -> RichContent:
    cli_cwd = artifact_dir.parent
    artifact_dir.mkdir(parents=True, exist_ok=True)
    try:
        payload = run_lark(
            ["vc", "+notes", "--minute-tokens", token, "--format", "json", "--output-dir", artifact_dir.name, "--as", "user"],
            cwd=cli_cwd,
        )
    except LarkCommandError:
        return RichContent(status="处理失败")
    return extract_rich_content(payload, read_file=lambda path: read_transcript_file(cli_cwd, path))


def extract_rich_content(payload: dict[str, Any], read_file) -> RichContent:
    artifacts = find_artifacts(payload)
    transcript_file = artifacts.get("transcript_file")
    transcript = read_file(transcript_file) if transcript_file else ""
    return RichContent(
        summary=stringify_artifact(artifacts.get("summary")),
        todos=stringify_artifact(artifacts.get("todos")) or "无",
        chapters=stringify_artifact(artifacts.get("chapters")),
        transcript=transcript,
    )


def find_artifacts(payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("data") or {}
    if isinstance(data.get("artifacts"), dict):
        return data["artifacts"]
    notes = data.get("notes") or []
    for note in notes:
        if isinstance(note, dict) and isinstance(note.get("artifacts"), dict):
            return note["artifacts"]
    for value in data.values():
        if isinstance(value, dict) and isinstance(value.get("artifacts"), dict):
            return value["artifacts"]
    return {}


def stringify_artifact(value: Any) -> str:
    if value in (None, "", []):
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(part for part in (stringify_artifact(item) for item in value) if part)
    if isinstance(value, dict):
        preferred = []
        for key in ("title", "text", "content", "summary_content", "summary", "todo", "name"):
            if isinstance(value.get(key), str) and value[key].strip():
                preferred.append(value[key].strip())
        return "\n".join(preferred) if preferred else json.dumps(value, ensure_ascii=False, indent=2)
    return str(value)


def read_transcript_file(base_dir: Path, path_value: str) -> str:
    path = Path(path_value)
    if not path.is_absolute():
        path = base_dir / path
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def create_record(base_token: str, table_id: str, payload: dict[str, Any]) -> str:
    result = run_lark(
        [
            "base",
            "+record-upsert",
            "--base-token",
            base_token,
            "--table-id",
            table_id,
            "--json",
            json.dumps(payload, ensure_ascii=False),
            "--as",
            "user",
        ]
    )
    record = result.get("data", {}).get("record", {})
    return str(record.get("record_id") or record.get("id") or "")


def update_record_link(base_token: str, table_id: str, record_id: str, minute: MinuteRecord) -> None:
    if not record_id or not minute.url:
        return
    run_lark(
        [
            "api",
            "PUT",
            f"/open-apis/bitable/v1/apps/{base_token}/tables/{table_id}/records/{record_id}",
            "--data",
            json.dumps({"fields": build_link_payload(minute)}, ensure_ascii=False),
            "--as",
            "user",
        ]
    )


def run_capture(args: argparse.Namespace) -> int:
    current_ms = now_ms()
    should_search, state = prepare_state(load_state(args.state_file), current_ms)
    if not should_search:
        if not args.dry_run:
            save_state(args.state_file, state)
        print(json.dumps({"captured": 0, "skipped": 0, "initialized": True}, ensure_ascii=False))
        return 0

    start_ms, end_ms = build_search_window(state, current_ms, args.overlap_minutes * 60 * 1000)
    search_items = search_owned_minutes(args.owner_ids, start_ms, end_ms)
    captured = 0
    skipped = 0
    skipped_video_meetings = 0
    planned: list[dict[str, Any]] = []
    video_tokens_by_day: dict[str, set[str]] = {}

    for item in search_items:
        minute = parse_search_item(item)
        if not minute.token:
            continue
        if args.owner_name and minute.owner_name and minute.owner_name != args.owner_name:
            skipped += 1
            continue
        if token_exists(args.base_token, args.table_id, minute.token):
            skipped += 1
            continue
        if args.source_mode == SOURCE_MODE_MANUAL and is_video_meeting_minute(minute, video_tokens_by_day):
            skipped += 1
            skipped_video_meetings += 1
            continue
        if args.dry_run:
            planned.append({TOKEN_FIELD: minute.token, "会议名称": minute.title, "会议日期": minute.start_time})
        else:
            rich = fetch_rich_content(minute.token, args.artifact_dir)
            payload = build_record_payload(minute, rich)
            record_id = create_record(args.base_token, args.table_id, payload)
            update_record_link(args.base_token, args.table_id, record_id, minute)
        captured += 1

    state["last_checked_at_ms"] = current_ms
    if not args.dry_run:
        save_state(args.state_file, state)
    result = {
        "captured": captured,
        "skipped": skipped,
        "skipped_video_meetings": skipped_video_meetings,
        "source_mode": args.source_mode,
        "checked_window": {"start": lark_time(start_ms), "end": lark_time(end_ms)},
    }
    if planned:
        result["planned"] = planned
    print(json.dumps(result, ensure_ascii=False))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Capture new Fu Qiang owned Lark Minutes into a Feishu Base inbox.")
    parser.add_argument("--base-token", default=DEFAULT_BASE_TOKEN)
    parser.add_argument("--table-id", default=DEFAULT_TABLE_ID)
    parser.add_argument("--owner-ids", default=DEFAULT_OWNER_IDS)
    parser.add_argument("--owner-name", default=DEFAULT_OWNER_NAME)
    parser.add_argument("--state-file", type=Path, default=DEFAULT_STATE_FILE)
    parser.add_argument("--artifact-dir", type=Path, default=DEFAULT_ARTIFACT_DIR)
    parser.add_argument("--overlap-minutes", type=int, default=DEFAULT_OVERLAP_MINUTES)
    parser.add_argument(
        "--source-mode",
        choices=[SOURCE_MODE_MANUAL, SOURCE_MODE_ALL],
        default=SOURCE_MODE_MANUAL,
        help="manual syncs only hand-created minutes; all syncs owned minutes including video meeting recordings.",
    )
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return run_capture(args)
    except LarkCommandError as exc:
        print(json.dumps({"ok": False, "error": exc.payload.get("error") or str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
