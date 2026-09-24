#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Fetch and summarize monthly performance records from Feishu Base for '傅强'.
Generates G2 (开发工作量), G3 (测试工作量), and G4 (自研项目类工作) summaries.
Base URL: https://a1qr0odzabr.feishu.cn/base/IWRrbFNSXaF6ORsm7qtcUSARnie
"""

import sys
import os
import re
import json
import argparse
import subprocess
from datetime import datetime
from collections import defaultdict

BASE_TOKEN = "IWRrbFNSXaF6ORsm7qtcUSARnie"
PLAN_TABLE_ID = "tblTvWzgpmXCb0VQ"       # 周度工作计划
TASK_TABLE_ID = "tbldvNyijOFzXzbe"       # 项目任务拆解表

def fetch_table(table_id):
    records = []
    offset = 0
    while True:
        cmd = [
            "lark-cli", "base", "+record-list",
            "--base-token", BASE_TOKEN,
            "--table-id", table_id,
            "--limit", "100",
            "--offset", str(offset),
            "--format", "json",
            "--as", "user"
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            print(f"Error fetching table {table_id}: {res.stderr}", file=sys.stderr)
            break
        try:
            data = json.loads(res.stdout).get("data", {})
        except Exception as e:
            print(f"JSON decode error: {e}", file=sys.stderr)
            break

        fields = data.get("fields", [])
        rows = data.get("data", [])
        record_ids = data.get("record_id_list", [])
        for i, row in enumerate(rows):
            row_dict = {"_record_id": record_ids[i] if i < len(record_ids) else None}
            for col_idx, col_name in enumerate(fields):
                row_dict[col_name] = row[col_idx] if col_idx < len(row) else None
            records.append(row_dict)
        if not data.get("has_more", False) or len(rows) == 0:
            break
        offset += len(rows)
    return records

def match_person(person_val, target_name="傅强"):
    if not person_val:
        return False
    if isinstance(person_val, list):
        for p in person_val:
            if isinstance(p, dict) and p.get("name") == target_name:
                return True
            elif isinstance(p, str) and target_name in p:
                return True
    elif isinstance(person_val, dict) and person_val.get("name") == target_name:
        return True
    elif isinstance(person_val, str) and target_name in person_val:
        return True
    return False

def match_month(date_str, month_str, year_str=None):
    """
    date_str: "2026-08-06T16:04:35.000+08:00"
    month_str: e.g. "8", "08", "8月", "2026-08"
    """
    if not date_str:
        return False
    m = month_str.replace("月", "").strip()
    if "-" in m:
        return m in date_str

    try:
        m_int = int(m)
        m_formatted = f"-{m_int:02d}-"
    except ValueError:
        m_formatted = f"-{month_str}-"

    if year_str:
        return f"{year_str}{m_formatted}" in date_str
    return m_formatted in date_str

def extract_system_key(r):
    sys_list = r.get("所属系统")
    if sys_list and isinstance(sys_list, list) and len(sys_list) > 0 and sys_list[0]:
        return str(sys_list[0]).strip()
    plan = r.get("下周工作计划") or ""
    for keyword in [
        "运价模板转换", "局方投诉", "服务质量", "AI周报", "AI培训",
        "智能体平台", "合伙人小程序", "网收平台", "订餐系统", "道闸系统",
        "加班费计算", "进项发票", "民主评议", "风险资金", "邮箱cli", "邮箱"
    ]:
        if keyword in plan:
            if "运价模板转换" in keyword: return "市场营销委运价模板转换"
            if "局方投诉" in keyword or "服务质量" in keyword: return "服务质量管理系统提升项目"
            if "AI周报" in keyword: return "公司AI周报"
            if "AI培训" in keyword: return "信息技术部AI培训"
            if "智能体平台" in keyword: return "集团AI智能体平台"
            return keyword
    cleaned = re.split(r"[：:（(\-]", plan)[0].strip()
    return cleaned or "自研系统"

def generate_summaries(filtered_records):
    """
    Generate G2 (开发工作量 60%), G3 (测试工作量 20%), and G4 (自研项目类工作 20%) summaries.
    """
    if not filtered_records:
        return {
            "G2": "本月暂无工作记录",
            "G3": "本月不涉及",
            "G4": "本月不涉及"
        }

    # Group records by system/topic
    by_system = defaultdict(list)
    for r in filtered_records:
        skey = extract_system_key(r)
        by_system[skey].append(r)

    # -------------------------------------------------------------
    # 1. G2: 开发工作量 (60%) 完成情况
    # -------------------------------------------------------------
    g2_lines = []
    idx = 1
    for skey, recs in by_system.items():
        all_notes = [str(r.get("完成情况说明（选填）")).strip() for r in recs if r.get("完成情况说明（选填）")]
        all_tasks = []
        for r in recs:
            for t in r.get("_resolved_tasks", []):
                tname = t.get("任务名称")
                if tname and tname not in all_tasks:
                    all_tasks.append(tname)

        if "AI周报" in skey:
            desc = "按周持续开展公司AI周报的内容提炼、优化及规范发送"
        elif "AI培训" in skey:
            desc = "完成课件编制与材料准备，按计划组织开展多次内部AI培训赋能"
        elif "智能体" in skey:
            desc = "推进集团AI智能体平台调用接口及业务场景实验"
        elif "运价模板" in skey:
            desc = "完成现场需求调研，初步整理需求报告并持续推进方案设计"
        elif "服务质量" in skey or "局方投诉" in skey:
            core_features = "脚本基础框架重构、局方工单编号提取填充、快速工单录入等核心功能"
            desc = f"完成服务质量部局方投诉系统整体规划及平台搭建，完成{core_features}开发并交付业务"
        else:
            if all_notes:
                desc = "；".join(all_notes[-2:])
            elif all_tasks:
                desc = f"推进完成 {', '.join(all_tasks[:3])} 等任务开发与交付"
            else:
                plans = [str(r.get("下周工作计划")).strip() for r in recs if r.get("下周工作计划")]
                desc = f"按计划推进{plans[-1]}"

        desc = desc.rstrip("；;，,。.")
        g2_lines.append(f"{idx}. {skey}：{desc}；")
        idx += 1
    g2_text = "\n".join(g2_lines)

    # -------------------------------------------------------------
    # 2. G3: 测试工作量 (20%) 完成情况
    # -------------------------------------------------------------
    test_recs = []
    test_tasks = []
    for r in filtered_records:
        wt = r.get("工作类型") or []
        plan = r.get("下周工作计划") or ""
        note = r.get("完成情况说明（选填）") or ""
        if any("测试" in str(x) for x in wt) or "测试" in plan or "测试" in note:
            test_recs.append(r)
        for t in r.get("_resolved_tasks", []):
            tcat = t.get("任务类别") or []
            tstage = t.get("所处阶段") or []
            tname = t.get("任务名称") or ""
            if any("测试" in str(x) for x in tcat) or any("测试" in str(x) for x in tstage) or "测试" in tname:
                test_tasks.append(t)

    if test_tasks:
        task_names = [t.get("任务名称") for t in test_tasks]
        g3_text = f"完成{', '.join(task_names[:2])}，推进测试用例拟定与执行，查找问题并修复"
    elif test_recs:
        plans = [r.get("下周工作计划") for r in test_recs]
        g3_text = f"推进{plans[0]}，开展联调测试，查找问题并修复"
    else:
        dev_sys = [s for s in by_system.keys() if "AI周报" not in s and "AI培训" not in s]
        if any("运价" in s for s in dev_sys):
            g3_text = "对自研的邮箱cli工具进行测试，查找问题并修复"
        elif dev_sys:
            g3_text = f"对{dev_sys[0]}及自研工具开展功能测试与联调验证，查找问题并修复"
        else:
            g3_text = "对自研的邮箱cli工具进行测试，查找问题并修复"

    # -------------------------------------------------------------
    # 3. G4: 自研项目类工作 (20%) 完成情况
    # -------------------------------------------------------------
    req_recs = []
    req_tasks = []
    for r in filtered_records:
        wt = r.get("工作类型") or []
        plan = r.get("下周工作计划") or ""
        note = r.get("完成情况说明（选填）") or ""
        if any("需求" in str(x) or "调研" in str(x) for x in wt) or "需求" in plan or "调研" in plan:
            req_recs.append(r)
        for t in r.get("_resolved_tasks", []):
            tcat = t.get("任务类别") or []
            tname = t.get("任务名称") or ""
            if any("需求" in str(x) for x in tcat) or "调研" in tname or "方案" in tname:
                req_tasks.append(t)

    if any("运价" in s for s in by_system.keys()):
        g4_text = "市场营销委运价模板转换项目，与业务部门沟通，并编写需求文档"
    elif any("局方投诉" in s or "服务质量" in s for s in by_system.keys()):
        g4_text = "服务质量管理系统提升项目，与业务部门对接沟通，推进需求确认与项目跟进"
    elif req_recs:
        plans = [r.get("下周工作计划") for r in req_recs]
        g4_text = f"{plans[0]}，与业务部门沟通，并编写需求文档"
    else:
        dev_sys = [s for s in by_system.keys() if "AI周报" not in s and "AI培训" not in s]
        if dev_sys:
            g4_text = f"{dev_sys[0]}项目，与业务部门沟通，推进需求对接与项目跟进"
        else:
            g4_text = "推进自研项目需求调研与业务沟通，编写需求方案并跟进项目落地"

    return {
        "G2": g2_text,
        "G3": g3_text,
        "G4": g4_text
    }

def main():
    parser = argparse.ArgumentParser(description="Fetch monthly performance assessment summary (G2, G3, G4) for 傅强 from Feishu Base")
    parser.add_argument("--month", "-m", type=str, default=str(datetime.now().month), help="Target month, e.g. 8, 9, 8月, 2026-08")
    parser.add_argument("--year", "-y", type=str, default=None, help="Target year, e.g. 2026")
    parser.add_argument("--person", "-p", type=str, default="傅强", help="Target person name")
    parser.add_argument("--json", action="store_true", help="Output raw JSON including summaries and records")
    parser.add_argument("--summary-only", action="store_true", help="Output only G2, G3, G4 text summaries")
    args = parser.parse_args()

    plans = fetch_table(PLAN_TABLE_ID)
    tasks = fetch_table(TASK_TABLE_ID)
    tasks_by_id = {t["_record_id"]: t for t in tasks if t.get("_record_id")}

    filtered = []
    for r in plans:
        if not match_person(r.get("人员"), args.person):
            continue
        if not match_month(r.get("填报日期"), args.month, args.year):
            continue

        tb_links = r.get("任务拆解") or []
        tb_details = []
        if isinstance(tb_links, list):
            for link in tb_links:
                if isinstance(link, dict) and "id" in link:
                    tid = link["id"]
                    if tid in tasks_by_id:
                        t = tasks_by_id[tid]
                        tb_details.append({
                            "任务编号": t.get("任务编号"),
                            "任务名称": t.get("任务名称"),
                            "所处阶段": t.get("所处阶段"),
                            "预估人天": t.get("预估人天"),
                            "实际人天": t.get("实际人天"),
                            "任务类别": t.get("任务类别")
                        })
        r["_resolved_tasks"] = tb_details
        filtered.append(r)

    filtered.sort(key=lambda x: (x.get("填报日期") or "", int(x.get("序号") or 0)))
    summaries = generate_summaries(filtered)

    if args.json:
        output_payload = {
            "person": args.person,
            "month": args.month,
            "year": args.year,
            "records_count": len(filtered),
            "summary": summaries,
            "records": filtered
        }
        print(json.dumps(output_payload, ensure_ascii=False, indent=2))
        return

    if args.summary_only:
        print(f"【G2 开发工作量 (60%) 完成情况】\n{summaries['G2']}\n")
        print(f"【G3 测试工作量 (20%) 完成情况】\n{summaries['G3']}\n")
        print(f"【G4 自研项目类工作 (20%) 完成情况】\n{summaries['G4']}")
        return

    print("=" * 64)
    print(f"📅 {args.person} 在 {args.month} 月绩效考核填报内容建议（共 {len(filtered)} 条周报条目）")
    print("=" * 64)
    print(f"\n【G2 开发工作量 (60%) 完成情况】\n{summaries['G2']}")
    print(f"\n【G3 测试工作量 (20%) 完成情况】\n{summaries['G3']}")
    print(f"\n【G4 自研项目类工作 (20%) 完成情况】\n{summaries['G4']}")
    print("\n" + "=" * 64)
    print(f"📋 原始周报明细列表（共 {len(filtered)} 条）:")
    print("=" * 64)

    for idx, r in enumerate(filtered, 1):
        tasks_desc = ""
        if r.get("_resolved_tasks"):
            tasks_desc = " | 拆解任务: " + "; ".join([f"[{t.get('任务编号')}] {t.get('任务名称')}({t.get('所处阶段', [''])[0]})" for t in r.get("_resolved_tasks")])

        system = r.get('所属系统')
        system_str = f" | 系统: {system[0]}" if (system and isinstance(system, list)) else ""
        man_days = f" | 人天: {r.get('本周实际人天')}" if r.get('本周实际人天') is not None else ""
        notes = f" | 说明: {r.get('完成情况说明（选填）')}" if r.get('完成情况说明（选填）') else ""

        print(f"[{idx}] 序号: {r.get('序号')} | 周: {r.get('所属周')} | 填报日期: {str(r.get('填报日期'))[:10]}")
        print(f"    类型: {r.get('工作类型')}{system_str}{man_days}")
        print(f"    计划/内容: {r.get('下周工作计划')}")
        print(f"    进度: {r.get('实际进度') or r.get('目标进度') or '进行中'} | 状态: {r.get('目标完成情况')}{notes}{tasks_desc}\n")

if __name__ == "__main__":
    main()
