#!/usr/bin/env python3
import argparse
import json
import sys
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

try:
    from chinese_calendar import get_holiday_detail, is_holiday, is_workday
except ImportError:
    get_holiday_detail = None
    is_holiday = None
    is_workday = None


WEEKDAY_NAMES = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
HOLIDAY_NAME_ZH = {
    "New Year's Day": "元旦",
    "Spring Festival": "春节",
    "Tomb-sweeping Day": "清明节",
    "Labour Day": "劳动节",
    "Dragon Boat Festival": "端午节",
    "Mid-autumn Festival": "中秋节",
    "National Day": "国庆节",
}


def read_env_file(required=True):
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.exists():
        if not required:
            return {}
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

    return config


def load_env():
    config = read_env_file()
    required = ["WECOM_CORP_ID", "WECOM_SECRET", "WECOM_USER_ID"]
    missing = [k for k in required if not config.get(k)]
    if missing:
        print(json.dumps({"error": f"缺少必要配置: {', '.join(missing)}"}))
        sys.exit(1)

    return config


def require_chinese_calendar():
    if is_workday is None or is_holiday is None or get_holiday_detail is None:
        raise RuntimeError("缺少依赖 chinese_calendar，请先安装：python3 -m pip install chinese-calendar")


def display_holiday_name(holiday_name):
    if not holiday_name:
        return None
    return HOLIDAY_NAME_ZH.get(holiday_name, holiday_name)


def workday_status(target_dt):
    require_chinese_calendar()

    date_str = target_dt.strftime("%Y-%m-%d")
    weekday_name = WEEKDAY_NAMES[target_dt.weekday()]
    target_date = target_dt.date()
    day_is_workday = is_workday(target_date)
    day_is_holiday = is_holiday(target_date)
    _, holiday_name = get_holiday_detail(target_date)
    holiday_label = display_holiday_name(holiday_name)

    if day_is_workday and holiday_label:
        reason = f"{date_str} 是调休工作日（{weekday_name}，{holiday_label}）"
    elif day_is_workday:
        reason = f"{date_str} 是工作日（{weekday_name}）"
    elif holiday_label:
        reason = f"{date_str} 是非工作日（{weekday_name}，{holiday_label}）"
    else:
        reason = f"{date_str} 是非工作日（{weekday_name}）"

    status = {
        "date": date_str,
        "weekday": weekday_name,
        "is_workday": day_is_workday,
        "is_holiday": day_is_holiday,
        "source": "chinese_calendar",
        "reason": reason,
    }
    if holiday_label:
        status["holiday_name"] = holiday_label
    return status


def iter_dates(start_dt, end_dt):
    current = start_dt.replace(hour=0, minute=0, second=0, microsecond=0)
    final = end_dt.replace(hour=0, minute=0, second=0, microsecond=0)
    while current <= final:
        yield current
        current += timedelta(days=1)


def build_non_workday_result(query_dt, status):
    date_str = query_dt.strftime("%Y-%m-%d")
    return {
        "query_start": date_str,
        "query_end": date_str,
        "total_records": 0,
        "records": [],
        "workday": status,
        "skipped": True,
        "summary": [f"{date_str} 不是工作日（{status['weekday']}），无需检查打卡。"],
    }


def build_no_workdays_result(start_dt, end_dt, statuses):
    return {
        "query_start": start_dt.strftime("%Y-%m-%d"),
        "query_end": end_dt.strftime("%Y-%m-%d"),
        "total_records": 0,
        "records": [],
        "workdays": statuses,
        "skipped": True,
        "summary": ["查询范围内没有工作日，无需检查打卡。"],
    }


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
    parser.add_argument("--workday-only", action="store_true", help="仅在工作日查询打卡，非工作日直接跳过")
    parser.add_argument("--check-workday-only", action="store_true", help="只检查是否工作日，不查询企业微信打卡API")
    args = parser.parse_args()

    if args.range:
        start_dt = datetime.strptime(args.range[0], "%Y-%m-%d")
        end_dt = datetime.strptime(args.range[1], "%Y-%m-%d").replace(hour=23, minute=59, second=59)
    elif args.date:
        start_dt = datetime.strptime(args.date, "%Y-%m-%d")
        end_dt = start_dt.replace(hour=23, minute=59, second=59)
    else:
        start_dt = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        end_dt = datetime.now().replace(hour=23, minute=59, second=59, microsecond=0)

    requested_start_dt = start_dt
    requested_end_dt = end_dt

    try:
        day_statuses = [workday_status(day) for day in iter_dates(start_dt, end_dt)]
    except RuntimeError as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        sys.exit(1)

    if args.check_workday_only:
        result = {
            "query_start": requested_start_dt.strftime("%Y-%m-%d"),
            "query_end": requested_end_dt.strftime("%Y-%m-%d"),
            "workdays": day_statuses,
        }
        if not args.range and day_statuses:
            result["workday"] = day_statuses[0]
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    if args.workday_only:
        workdays = [status for status in day_statuses if status["is_workday"]]
        if not workdays:
            if args.range:
                result = build_no_workdays_result(requested_start_dt, requested_end_dt, day_statuses)
            else:
                result = build_non_workday_result(requested_start_dt, day_statuses[0])
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return

        first_workday = datetime.strptime(workdays[0]["date"], "%Y-%m-%d")
        last_workday = datetime.strptime(workdays[-1]["date"], "%Y-%m-%d")
        start_dt = first_workday
        end_dt = last_workday.replace(hour=23, minute=59, second=59)

    config = load_env()

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
        current = requested_start_dt
        status_by_date = {status["date"]: status for status in day_statuses}
        while current <= requested_end_dt:
            d = current.strftime("%Y-%m-%d")
            status = status_by_date.get(d)
            if args.workday_only and status and not status["is_workday"]:
                summaries.append(f"{d} 不是工作日（{status['weekday']}），无需检查打卡。")
                current += timedelta(days=1)
                continue
            day_records = by_date.get(d, [])
            summaries.append(build_summary(day_records, d))
            current += timedelta(days=1)
    else:
        query_date = args.date if args.date else datetime.now().strftime("%Y-%m-%d")
        day_records = by_date.get(query_date, [])
        summaries.append(build_summary(day_records, query_date))

    result = {
        "query_start": requested_start_dt.strftime("%Y-%m-%d"),
        "query_end": requested_end_dt.strftime("%Y-%m-%d"),
        "total_records": len(records),
        "records": formatted_records,
        "summary": summaries,
    }
    if args.workday_only:
        result["workday_only"] = True
        result["api_query_start"] = start_dt.strftime("%Y-%m-%d")
        result["api_query_end"] = end_dt.strftime("%Y-%m-%d")
    if args.range:
        result["workdays"] = day_statuses
    elif day_statuses:
        result["workday"] = day_statuses[0]

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
