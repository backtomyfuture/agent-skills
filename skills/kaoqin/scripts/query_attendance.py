#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
月度绩效考核出勤查询脚本 (kaoqin 内置)
用于从海航 OA 查询指定月份的休假公文并生成月度绩效考核 G7 出勤情况总结。
"""

import argparse
import datetime
import json
import os
import re
import subprocess
import sys
import time
from collections import defaultdict


def run_command(cmd, timeout=40, retries=2, retry_delay=1.5):
    """运行外部命令并返回 stdout 字符串，支持失败重试"""
    for attempt in range(retries + 1):
        try:
            res = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
            if res.returncode == 0 and res.stdout.strip():
                return res.stdout.strip()
            if attempt < retries:
                time.sleep(retry_delay)
        except Exception:
            if attempt < retries:
                time.sleep(retry_delay)
    return None


def parse_month_arg(month_str, default_year=None):
    """解析月份参数，返回 (year, month)"""
    now = datetime.datetime.now()
    year = default_year or now.year

    if not month_str:
        return year, now.month

    month_str = str(month_str).strip()

    # 匹配 2026-08 或 2026/08 或 2026.08
    m_ym = re.match(r"^(\d{4})[-/.](\d{1,2})$", month_str)
    if m_ym:
        return int(m_ym.group(1)), int(m_ym.group(2))

    # 匹配 2026年8月 或 2026年8
    m_cym = re.match(r"^(\d{4})年(\d{1,2})月?$", month_str)
    if m_cym:
        return int(m_cym.group(1)), int(m_cym.group(2))

    # 匹配 8月 或 8
    m_m = re.match(r"^(\d{1,2})月?$", month_str)
    if m_m:
        return year, int(m_m.group(1))

    raise ValueError(f"无法识别的月份格式: {month_str}")


def normalize_leave_type(type_raw):
    """标准化休假类型"""
    if not type_raw:
        return "休假"
    if "年休假" in type_raw or "年假" in type_raw or "延期年休假" in type_raw:
        return "年休假"
    if "倒休" in type_raw or "调休" in type_raw or "补休" in type_raw:
        return "倒休"
    if "事假" in type_raw:
        return "事假"
    if "病假" in type_raw:
        return "病假"
    if "婚假" in type_raw:
        return "婚假"
    if "产假" in type_raw or "生育" in type_raw:
        return "产假"
    if "丧假" in type_raw:
        return "丧假"
    if "育儿假" in type_raw:
        return "育儿假"
    if "陪护假" in type_raw or "护理假" in type_raw:
        return "陪护假"
    if "探亲假" in type_raw:
        return "探亲假"
    return type_raw


def extract_leave_records(text, default_year):
    """
    从请示内容中精准解析休假记录
    返回列表: [{'date': datetime.date, 'period': '全天'/'上午'/'下午', 'type': '年休假', 'days': 1.0, 'raw': str}]
    """
    records = []
    if not text:
        return records

    # 清洗特殊字符
    clean_text = text.replace('\xa0', ' ').replace('\u3000', ' ').strip()

    # 1. 识别休假类型
    used_type = None
    m_type = re.search(r"(?:使用|申请|请休)(?:\d{4}年?|\d{1,2}月)?(?:度)?(延期年休假|年休假|年假|倒休|调休|补休|事假|病假|婚假|产假|育儿假|陪护假|丧假)", clean_text)
    if m_type:
        used_type = normalize_leave_type(m_type.group(1))
    else:
        m_fallback = re.search(r"(延期年休假|年休假|年假|倒休|调休|补休|事假|病假|婚假|产假|育儿假|陪护假|丧假)", clean_text)
        if m_fallback:
            used_type = normalize_leave_type(m_fallback.group(1))

    # 2. 识别本次使用的总天数/小时数
    total_days = None
    m_use_days = re.search(r"本次使用(\d+(?:\.\d+)?)天", clean_text)
    if m_use_days:
        total_days = float(m_use_days.group(1))
    else:
        m_use_hours = re.search(r"本次使用(\d+(?:\.\d+)?)小时", clean_text)
        if m_use_hours:
            total_days = float(m_use_hours.group(1)) / 8.0
        else:
            m_use_direct = re.search(r"使用.*?(\d+(?:\.\d+)?)天", clean_text)
            if m_use_direct:
                total_days = float(m_use_direct.group(1))
            else:
                m_use_h_direct = re.search(r"使用.*?(\d+(?:\.\d+)?)小时", clean_text)
                if m_use_h_direct:
                    total_days = float(m_use_h_direct.group(1)) / 8.0

    # 3. 提取申请的日期语句
    apply_clause = clean_text
    m_apply = re.search(r"申请(.*?)(?:使用|20\d\d年剩余|本次使用|使用前|原有开发工作|妥否|望领导|$)", clean_text, re.DOTALL)
    if m_apply:
        apply_clause = m_apply.group(1)

    # 模式 A: 半天组合 "3月12日下午和3月13日上午"
    half_pattern = r"(?:(\d{4})年)?(\d{1,2})月(\d{1,2})日?(?:（[^）]+）|\([^)]+\))?(上午|下午)"
    half_matches = list(re.finditer(half_pattern, apply_clause))
    if half_matches:
        for match in half_matches:
            y = int(match.group(1)) if match.group(1) else default_year
            m = int(match.group(2))
            d = int(match.group(3))
            period = match.group(4)
            try:
                date_val = datetime.date(y, m, d)
                records.append({
                    "date": date_val,
                    "period": period,
                    "type": used_type or "休假",
                    "days": 0.5,
                    "raw": match.group(0),
                })
            except Exception:
                pass

    # 模式 B: 连续范围型 "6月15日至6月17日" 或 "2026年3月10日至2026年3月13日"
    if not records:
        range_pattern = r"(?:(\d{4})年)?(\d{1,2})月(\d{1,2})日?\s*(?:至|到|-|~)\s*(?:(\d{4})年)?(?:(\d{1,2})月)?(\d{1,2})日"
        range_matches = list(re.finditer(range_pattern, apply_clause))
        for match in range_matches:
            y1 = int(match.group(1)) if match.group(1) else default_year
            m1 = int(match.group(2))
            d1 = int(match.group(3))
            y2 = int(match.group(4)) if match.group(4) else y1
            m2 = int(match.group(5)) if match.group(5) else m1
            d2 = int(match.group(6))

            try:
                start_date = datetime.date(y1, m1, d1)
                end_date = datetime.date(y2, m2, d2)
                date_list = []
                cur = start_date
                while cur <= end_date:
                    date_list.append(cur)
                    cur += datetime.timedelta(days=1)

                day_per_item = (total_days / len(date_list)) if total_days else 1.0
                for dt in date_list:
                    records.append({
                        "date": dt,
                        "period": "全天",
                        "type": used_type or "休假",
                        "days": day_per_item,
                        "raw": match.group(0),
                    })
            except Exception:
                pass

    # 模式 C: 单日或顿号枚举 "8月4日（星期二）" 或 "7月31日（星期五）" 或 "4月28日、4月29日"
    if not records:
        single_pattern = r"(?:(\d{4})年)?(\d{1,2})月(\d{1,2})日"
        single_matches = list(re.finditer(single_pattern, apply_clause))
        if single_matches:
            num_dates = len(single_matches)
            day_per_item = (total_days / num_dates) if total_days else 1.0
            for match in single_matches:
                y = int(match.group(1)) if match.group(1) else default_year
                m = int(match.group(2))
                d = int(match.group(3))
                try:
                    date_val = datetime.date(y, m, d)
                    records.append({
                        "date": date_val,
                        "period": "全天",
                        "type": used_type or "休假",
                        "days": day_per_item,
                        "raw": match.group(0),
                    })
                except Exception:
                    pass

    # 去重
    unique_records = []
    seen = set()
    for r in records:
        key = (r["date"], r["period"])
        if key not in seen:
            seen.add(key)
            unique_records.append(r)

    return unique_records


def query_attendance(target_year, target_month):
    """
    查询指定年月的绩效考核出勤数据并解析
    """
    cmd = f'opencli hnaoa query --year {target_year} --category "我呈报的公文" --limit 50 -f json'
    output = run_command(cmd)
    if not output:
        return {
            "success": False,
            "error": "未能从海航OA获取公文数据，请确认已登录OA系统",
            "year": target_year,
            "month": target_month,
            "records": [],
            "stats": {},
            "summary_text": f"{target_month}月无休假；无异常出勤情况",
        }

    try:
        docs = json.loads(output)
    except Exception as e:
        return {
            "success": False,
            "error": f"解析OA公文JSON失败: {e}",
            "year": target_year,
            "month": target_month,
            "records": [],
            "stats": {},
            "summary_text": f"{target_month}月无休假；无异常出勤情况",
        }

    target_month_records = []
    processed_docs = []

    for doc in docs:
        doc_type = doc.get("type", "")
        title = doc.get("title", "") or doc.get("flow_title", "")
        part_id = doc.get("part_id", "")

        # 仅针对休假相关的公文进行详情查看
        is_leave_doc = (
            doc_type == "HRM休假申请"
            or "休假" in title
            or "补休" in title
            or "年假" in title
            or "倒休" in title
        )
        if not is_leave_doc or not part_id:
            continue

        view_cmd = f'opencli hnaoa view "{part_id}" --year {target_year} -f json'
        view_out = run_command(view_cmd)
        if not view_out:
            continue

        try:
            vdata = json.loads(view_out)
            if isinstance(vdata, list) and len(vdata) > 0:
                vdata = vdata[0]
            request_content = vdata.get("request_content", "")
        except Exception:
            request_content = ""

        if not request_content:
            continue

        records = extract_leave_records(request_content, default_year=target_year)

        # 过滤出落在目标月份的记录
        matched_in_doc = [r for r in records if r["date"].year == target_year and r["date"].month == target_month]
        if matched_in_doc:
            processed_docs.append({
                "part_id": part_id,
                "title": title,
                "records": matched_in_doc,
                "content": request_content,
            })
            target_month_records.extend(matched_in_doc)

    # 排序
    target_month_records.sort(key=lambda x: (x["date"], 0 if x["period"] in ["全天", "上午"] else 1))

    # 统计各类假期天数
    stats = defaultdict(float)
    for r in target_month_records:
        stats[r["type"]] += r["days"]

    def format_days(d):
        if d.is_integer():
            return f"{int(d)}"
        elif round(d, 2) == 0.25:
            return "0.25"
        elif round(d, 2) == 0.5 or round(d, 1) == 0.5:
            return "0.5"
        elif round(d, 2) == 0.75:
            return "0.75"
        else:
            return f"{d:.2f}".rstrip("0").rstrip(".")

    # 按照固定顺序排列假期类型：年休假、倒休、事假、病假等
    type_order = ["年休假", "倒休", "事假", "病假", "婚假", "产假", "育儿假", "陪护假", "丧假", "探亲假"]
    sorted_types = sorted(stats.keys(), key=lambda t: type_order.index(t) if t in type_order else 99)

    if stats:
        items = [f"{t}{format_days(stats[t])}天" for t in sorted_types]
        leave_str = "，".join(items)
        summary_text = f"{target_month}月{leave_str}；无异常出勤情况"
    else:
        summary_text = f"{target_month}月无休假；无异常出勤情况"

    return {
        "success": True,
        "year": target_year,
        "month": target_month,
        "records": target_month_records,
        "stats": {k: format_days(v) for k, v in stats.items()},
        "docs": processed_docs,
        "summary_text": summary_text,
    }


def main():
    parser = argparse.ArgumentParser(description="获取指定月份的月度绩效考核出勤情况，用于填充 G7")
    parser.add_argument("month", nargs="?", default="", help="月份，如 8、8月、2026年8月、2026-08")
    parser.add_argument("--year", type=int, default=None, help="指定年份，默认为当前年")
    parser.add_argument("-f", "--format", choices=["summary", "json", "detail"], default="summary", help="输出格式")

    args = parser.parse_args()

    try:
        year, month = parse_month_arg(args.month, args.year)
    except Exception as e:
        print(f"错误: {e}", file=sys.stderr)
        sys.exit(1)

    res = query_attendance(year, month)

    if args.format == "summary":
        print(res["summary_text"])
    elif args.format == "json":
        output_data = dict(res)
        output_data["records"] = [
            {**r, "date": r["date"].strftime("%Y-%m-%d")} for r in res["records"]
        ]
        for d in output_data["docs"]:
            d["records"] = [{**r, "date": r["date"].strftime("%Y-%m-%d")} for r in d["records"]]
        print(json.dumps(output_data, ensure_ascii=False, indent=2))
    elif args.format == "detail":
        print(f"【{res['year']}年{res['month']}月度绩效考核统计】")
        print(f"总结: {res['summary_text']}")
        if res["records"]:
            print("\n明细:")
            for r in res["records"]:
                period_str = f" ({r['period']})" if r["period"] != "全天" else ""
                print(f"- {r['date'].strftime('%Y-%m-%d')}{period_str}: {r['type']} {format_days_str(r['days'])}天")


def format_days_str(d):
    if isinstance(d, (int, float)):
        if float(d).is_integer():
            return f"{int(d)}"
        return f"{d}"
    return str(d)


if __name__ == "__main__":
    main()
