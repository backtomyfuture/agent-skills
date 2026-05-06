---
name: wecom-checkin
description: |
  通过企业微信API查询打卡状态。用于检查自己是否已经打卡（上班/下班），支持查询今天或指定日期的打卡记录，并可先判断是否工作日，非工作日跳过打卡检查。
  当用户提到"打卡"、"是否打卡"、"查打卡"、"考勤打卡"、"签到"、"上班打卡"、"下班打卡"、
  "有没有打卡"、"忘记打卡"、"打卡提醒"、"今天是否工作日"、"工作日检查"、"checkin"时，使用此skill。
  即使用户只是说"帮我看看打没打卡"、"查一下今天打卡了没"、"我打卡了吗"，也应该触发。
---

# 企业微信打卡状态查询

通过企业微信API查询员工打卡记录，用于快速确认是否已打卡。工作日判断使用 `chinese_calendar`，能识别中国法定节假日和调休工作日。

## 配置

skill目录下的 `.env` 文件存放所有必要配置：

```
WECOM_CORP_ID=你的企业ID
WECOM_SECRET=打卡应用的Secret
WECOM_AGENT_ID=打卡应用的AgentId
WECOM_USER_ID=你的企业微信UserId
```

如果 `.env` 不存在或配置不完整，提示用户创建并填写。
如果只运行 `--check-workday-only`，或 `--workday-only` 判断为非工作日并跳过查询，则不需要企业微信配置。
如果缺少工作日判断依赖，先安装：`python3 -m pip install chinese-calendar`。

## 使用方式

运行skill目录下的Python脚本来查询打卡记录：

```bash
python3 <skill-dir>/scripts/check_attendance.py [--date YYYY-MM-DD] [--range YYYY-MM-DD YYYY-MM-DD] [--workday-only] [--check-workday-only]
```

参数说明：
- 不带参数：查询今天的打卡记录
- `--date 2026-03-27`：查询指定日期
- `--range 2026-03-01 2026-03-27`：查询日期范围
- `--workday-only`：先判断是否工作日；非工作日直接返回跳过结果，不查询企业微信API
- `--check-workday-only`：只判断是否工作日，不查询打卡记录

默认工作流：
- 用户问“今天打卡了吗”“帮我看看打没打卡”“打卡提醒”时，优先运行 `--workday-only`。
- 用户明确要查原始打卡记录、补查周末记录或指定“无论是否工作日都查”时，不加 `--workday-only`。
- 用户只问“今天是不是工作日”时，运行 `--check-workday-only`。

脚本会自动从skill目录下的 `.env` 读取配置。

## 输出解读

脚本输出JSON格式数据，包含以下关键字段：

- `query_start` / `query_end`：查询日期范围
- `api_query_start` / `api_query_end`：启用 `--workday-only` 时，实际请求企业微信API的工作日范围
- `workday` / `workdays`：工作日判断结果，包含 `is_workday`、`weekday`、`source`、`reason`
- `skipped`：如果为 `true`，表示因为非工作日或查询范围内没有工作日而跳过企业微信API查询
- `records`：打卡记录列表，每条记录包含：
  - `checkin_type`：上班打卡 / 下班打卡 / 外出打卡
  - `checkin_time`：打卡时间（可读格式）
  - `exception_type`：异常类型（正常/迟到/早退/未打卡等）
  - `location_title`：打卡地点
- `summary`：简要汇总（已打上班卡/未打上班卡等）

根据输出结果，用简洁的中文告知用户打卡状态。例如：
- "今天已打上班卡（09:02），尚未打下班卡。"
- "今天上班卡（08:55）和下班卡（18:05）都已打，一切正常。"
- "今天还没有任何打卡记录，请记得打卡！"
- "今天不是工作日（周六），无需检查打卡。"

如果遇到API错误（如access_token过期、权限不足），将错误信息翻译为用户友好的提示。
