#!/usr/bin/env python3
import argparse
import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path


def load_env():
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.exists():
        print(json.dumps({"error": f".env 文件不存在: {env_path}，请参考 .env.example 创建"}))
        sys.exit(1)

    config = {}
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, val = line.split("=", 1)
                config[key.strip()] = val.strip()

    required = ["WECOM_CORP_ID", "WECOM_SECRET", "WECOM_USER_ID"]
    missing = [k for k in required if not config.get(k)]
    if missing:
        print(json.dumps({"error": f"缺少必要配置: {', '.join(missing)}"}))
        sys.exit(1)

    return config


def get_access_token(corp_id, secret):
    url = f"https://qyapi.weixin.qq.com/cgi-bin/gettoken?corpid={corp_id}&corpsecret={secret}"
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read().decode())

    if data.get("errcode", 0) != 0:
        return None, f"获取access_token失败: {data.get('errmsg', '未知错误')}"
    return data["access_token"], None


def get_checkin_data(access_token, user_ids, start_time, end_time):
    url = f"https://qyapi.weixin.qq.com/cgi-bin/checkin/getcheckindata?access_token={access_token}"
    body = json.dumps({
        "opencheckindatatype": 3,
        "starttime": start_time,
        "endtime": end_time,
        "useridlist": user_ids,
    }).encode()

    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read().decode())

    if data.get("errcode", 0) != 0:
        return None, f"获取打卡数据失败: {data.get('errmsg', '未知错误')}"
    return data.get("checkindata", []), None


def format_timestamp(ts):
    return datetime.fromtimestamp(ts).strftime("%H:%M:%S")


def format_date(ts):
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d")


def build_summary(records, query_date):
    if not records:
        return f"{query_date} 没有任何打卡记录，请记得打卡！"

    types = {}
    for r in records:
        ct = r["checkin_type"]
        types.setdefault(ct, []).append(r)

    parts = []
    has_morning = "上班打卡" in types
    has_evening = "下班打卡" in types

    if has_morning:
        t = types["上班打卡"][0]
        exc = t["exception_type"]
        time_str = format_timestamp(t["checkin_time"])
        status = f"（{exc}）" if exc and exc != "正常" else ""
        parts.append(f"已打上班卡（{time_str}）{status}")
    else:
        parts.append("未打上班卡")

    if has_evening:
        t = types["下班打卡"][-1]
        exc = t["exception_type"]
        time_str = format_timestamp(t["checkin_time"])
        status = f"（{exc}）" if exc and exc != "正常" else ""
        parts.append(f"已打下班卡（{time_str}）{status}")
    else:
        parts.append("未打下班卡")

    if "外出打卡" in types:
        parts.append(f"外出打卡{len(types['外出打卡'])}次")

    return f"{query_date} " + "，".join(parts) + "。"


def main():
    parser = argparse.ArgumentParser(description="企业微信打卡状态查询")
    parser.add_argument("--date", help="查询指定日期 (YYYY-MM-DD)")
    parser.add_argument("--range", nargs=2, metavar=("START", "END"), help="查询日期范围 (YYYY-MM-DD YYYY-MM-DD)")
    args = parser.parse_args()

    config = load_env()

    if args.range:
        start_dt = datetime.strptime(args.range[0], "%Y-%m-%d")
        end_dt = datetime.strptime(args.range[1], "%Y-%m-%d").replace(hour=23, minute=59, second=59)
    elif args.date:
        start_dt = datetime.strptime(args.date, "%Y-%m-%d")
        end_dt = start_dt.replace(hour=23, minute=59, second=59)
    else:
        start_dt = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        end_dt = datetime.now().replace(hour=23, minute=59, second=59, microsecond=0)

    start_ts = int(start_dt.timestamp())
    end_ts = int(end_dt.timestamp())

    token, err = get_access_token(config["WECOM_CORP_ID"], config["WECOM_SECRET"])
    if err:
        print(json.dumps({"error": err}, ensure_ascii=False))
        sys.exit(1)

    records, err = get_checkin_data(token, [config["WECOM_USER_ID"]], start_ts, end_ts)
    if err:
        print(json.dumps({"error": err}, ensure_ascii=False))
        sys.exit(1)

    formatted_records = []
    for r in records:
        formatted_records.append({
            "userid": r.get("userid"),
            "groupname": r.get("groupname"),
            "checkin_type": r.get("checkin_type"),
            "exception_type": r.get("exception_type"),
            "checkin_time": format_timestamp(r.get("checkin_time", 0)),
            "checkin_date": format_date(r.get("checkin_time", 0)),
            "location_title": r.get("location_title"),
            "location_detail": r.get("location_detail"),
        })

    # Group by date for summary
    by_date = {}
    for r in records:
        d = format_date(r.get("checkin_time", 0))
        by_date.setdefault(d, []).append(r)

    summaries = []
    if args.range:
        current = start_dt
        while current <= end_dt:
            d = current.strftime("%Y-%m-%d")
            day_records = by_date.get(d, [])
            summaries.append(build_summary(day_records, d))
            current += timedelta(days=1)
    else:
        query_date = args.date if args.date else datetime.now().strftime("%Y-%m-%d")
        day_records = by_date.get(query_date, [])
        summaries.append(build_summary(day_records, query_date))

    result = {
        "query_start": start_dt.strftime("%Y-%m-%d"),
        "query_end": end_dt.strftime("%Y-%m-%d"),
        "total_records": len(records),
        "records": formatted_records,
        "summary": summaries,
    }

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
