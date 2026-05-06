---
name: lark-minutes-base-sync
description: "把飞书妙记作为随身信息入口同步到飞书多维表格 inbox。用户提到飞书妙记、iPhone 录音、手工上传音频、随身信息入口、agent inbox、新妙记同步到 Base、外部定时器高频调用、同步脚本排障、状态文件或来源过滤时必须使用本 skill。默认只同步傅强手工创建/上传/录音的新妙记，跳过视频会议自动生成的妙记；不做历史回填，短录音也捕获；新记录把首列 `会议名称` 写成妙记链接，并只从飞书同步逐字稿，AI总结、待办和章节由 Base 或后续 agent 基于逐字稿生成。"
metadata:
  requires:
    bins: ["lark-cli", "python3"]
---

# 飞书妙记 Capture

这个 skill 把飞书妙记当成随身信息入口：iPhone 录音或手工上传进入飞书妙记，脚本把新妙记的元数据和逐字稿写入 Base。首列 `会议名称` 是 Base 原生超链接对象，显示文字用妙记标题，链接指向妙记 URL。飞书自己的 AI artifacts（总结、待办、章节）不作为同步来源；后续由 Base 或 agent 基于 `转写内容` 生成 `AI总结`、`待办事项` 和 `章节要点`。

固定目标：

- Base URL: `https://a1qr0odzabr.feishu.cn/base/AArpb8s1daYUytsAxWgciWeVnud`
- Base token: `AArpb8s1daYUytsAxWgciWeVnud`
- 表：`妙记列表`
- table id: `tbloqAEhgMnSXMi8`
- 状态文件：`~/.lark-minutes-base-sync/state.json`

## 运行命令

外部调度器或手动调用时只运行这一条：

```bash
python3 /Users/jarod/.agents/skills/lark-minutes-base-sync/scripts/sync_minutes.py
```

在 Hermes Agent 的 terminal/cron 工具上下文中，`lark-cli` 会检测 `HERMES_*` 环境变量并尝试切到未绑定的 `hermes` workspace，可能报 `hermes context detected but lark-cli not bound to hermes workspace`、`not configured` 或 `FEISHU_APP_ID not found in ~/.hermes/.env`。脚本的 `run_lark()` 已内置清理所有 `HERMES_*` 环境变量，确保使用本机已有的 local lark-cli 配置；如需手动排查，也可直接运行：

```bash
python3 /Users/jarod/.agents/skills/lark-minutes-base-sync/scripts/sync_minutes.py
```

预览但不写入：

```bash
python3 /Users/jarod/.agents/skills/lark-minutes-base-sync/scripts/sync_minutes.py --dry-run
```

默认只同步手工创建的妙记。如果临时需要包含视频会议自动生成的妙记，显式传：

```bash
python3 /Users/jarod/.agents/skills/lark-minutes-base-sync/scripts/sync_minutes.py --source-mode all
```

## 运行规则

- 只查 `lark-cli minutes +search --owner-ids me`，也就是傅强拥有的妙记。
- 不查 `participant-ids`，避免把别人拥有但我参与/可见的妙记同步进来。
- 默认 `--source-mode manual`，只同步手工创建、iPhone 新录音或手工上传生成的妙记。
- 视频会议自动生成的妙记会被跳过。脚本按新妙记所在日期查询 `vc +search`，再用 `vc +recording` 批量反查当天视频会议录制的 `minute_token`；命中同一个 token 即判定为视频会议自动妙记。
- manual 模式下，如果搜索结果缺少可解析的开始日期，脚本必须失败并等待下次重试，避免把来源不明的新妙记误写入随身信息入口。
- 只有显式传 `--source-mode all` 时，才把视频会议自动生成的妙记也纳入同步。
- 不排除短录音。
- 不做历史回填。第一次运行没有状态文件时，只初始化基线并退出。
- 高频运行时只查上次检查时间附近的新窗口；默认向前重叠 10 分钟，避免处理延迟导致漏捕获。
- 只对新入库 token 调用 `/open-apis/minutes/v1/minutes/<minute_token>/transcript` 下载逐字稿；不调用 `vc +notes`，也不读取飞书 artifacts。
- 已存在 token 会跳过，不重复拉取大文本。

## 写入字段

脚本只写存储字段；`最后同步时间` 是 Base 的更新时间系统字段，由飞书自动维护：

- `妙记Token`
- `会议名称`：Base 原生超链接对象，显示文字用妙记标题，链接用妙记 URL
- `AI总结`：同步脚本不写，由 Base 或后续 agent 基于逐字稿生成
- `待办事项`：同步脚本不写，由 Base 或后续 agent 基于逐字稿生成
- `章节要点`：同步脚本不写，由 Base 或后续 agent 基于逐字稿生成
- `转写内容`
- `组织者`
- `会议日期`
- `会议时长`
- `同步状态`：逐字稿同步成功写 `已捕获`；逐字稿拉取失败时写 `处理失败`

## 妙记链接写入规则

不再维护单独的 `妙记链接` 字段。`会议名称` 字段必须保持 URL 样式文本，并直接写 Base 原生超链接对象：

```json
{"会议名称":{"text":"会议名称","link":"https://.../minutes/<minute_token>"}}
```

终端里 `base +record-list` 可能显示为 `[会议名称](URL)`，这是 CLI 的 Markdown 展示；原始 API 值应是 `{text, link}`。

`base +record-upsert` / `base +record-batch-update` 不支持直接写 `{text, link}` 形态的 URL 对象。脚本应先用 `base +record-upsert` 创建普通存储字段，再用原生记录更新接口单独把 `会议名称` 更新为超链接对象：

```bash
lark-cli api PUT /open-apis/bitable/v1/apps/<base_token>/tables/<table_id>/records/<record_id> \
  --data '{"fields":{"会议名称":{"text":"会议名称","link":"https://.../minutes/<minute_token>"}}}' \
  --as user
```

后续 agent 处理阶段应优先读取 Base 中的 `转写内容`，生成或更新 `AI总结`、`待办事项`、`章节要点`，并更新 `同步状态`。

## 验证

修改脚本后跑：

```bash
python3 /Users/jarod/.agents/skills/lark-minutes-base-sync/tests/test_sync_minutes.py
python3 -m py_compile /Users/jarod/.agents/skills/lark-minutes-base-sync/scripts/sync_minutes.py
python3 /Users/jarod/.agents/skills/lark-minutes-base-sync/scripts/sync_minutes.py --dry-run
```

## 故障处理

如果 `minutes +search`、`vc +search`、`vc +recording`、`api GET /open-apis/minutes/v1/minutes/<minute_token>/transcript` 或 Base 写入返回 `missing_scope`，按 `lark-cli` 输出的 hint 做增量授权。不要切到 bot 身份；这个入口读取的是用户自己的妙记、用户可见的视频会议记录和用户可访问的 Base。

来源判定失败时不要静默同步；保持脚本失败并让外部调度下次重试，避免把视频会议自动妙记误写进随身信息入口。

如果错误里出现 `cannot determine source`，先检查 `minutes +search` 返回的 `meta_data.description` 是否包含 `开始时间`。不要为了绕过错误改用 `--source-mode all`，除非用户明确要把视频会议自动生成的妙记也写入 Base。
