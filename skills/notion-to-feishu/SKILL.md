---
name: notion-to-feishu
description: >
  将 Notion 页面无缝同步并转换为高保真、美观的飞书云文档（Docx）。
  采用 Notion 原生 AST 树直转飞书 XML 架构，深度支持：
  Notion Callout 精准主题配色与卡片内嵌、关键词彩色胶囊徽章（Pills）、多栏排版（Grid 双栏/多栏对比）、
  Mermaid 流程图自动编译为飞书原生交互画板（Whiteboard）、问答与折叠内容原生收起（Toggle / Folded Headings）、
  表格浅灰表头排版、任务清单（Checkbox）、LaTeX 公式，并自动为当前用户配置 full_access（可管理权限）。
  当用户提出“将 Notion 同步到飞书”、“Notion 转飞书”、“把 Notion 页面转成飞书文档”、“notion to feishu”、“notion to lark”、
  “导入 Notion 到飞书”或提供 Notion 链接并要求转成飞书文档时必须使用此技能。
---

# Notion → 飞书文档（Docx）高保真同步技能

本技能基于 **Notion 原生 AST 直转 飞书 Docx XML 引擎**，将 Notion 页面一键无损同步为排版精美、高度保真的飞书云文档。

---

## 🌟 核心排版特性与视觉还原

| 原 Notion 元素 | 转换后的飞书 Docx 元素 | 视觉与排版优化说明 |
| :--- | :--- | :--- |
| **🔑 关键词 / Code 标签** | **多彩胶囊标签 (Pills)** (`<span background-color="light-*" text-color="*">`) | 自动识别关键词容器与代码标签，按调色板渲染为蓝/紫/绿/橙/红/黄的多彩圆角胶囊标签 |
| **📦 Callout / 高亮块** | **飞书原生主题卡片** (`<callout emoji="..." background-color="..." border-color="...">`) | 精准继承 Emoji 图标与主题底色（蓝/黄/红/绿/灰/紫/橙），子段落、子列表完整封装在卡片内部 |
| **⚖️ 双栏/多栏布局 (`column_list`)** | **飞书原生栅格 (`<grid><column width-ratio="...">`)** | 自动按比例切分为并排多栏（如 50%:50% 对比卡片），告别杂乱的单栏串联堆叠 |
| **📊 Mermaid 流程图** | **飞书原生交互画板 (Whiteboard)** (`<whiteboard type="mermaid">`) | 自动识别 `flowchart`、`graph`、`sequenceDiagram` 并编译为矢量可缩放交互画板 |
| **▶️ 折叠列表 / Toggle** | **飞书原生折叠标题 / Toggle** (`style.folded: true`) | 默认折叠收起，带交互小三角 `▶`，点击展开，提升长文与问答浏览体验 |
| **📋 数据表格 (`table`)** | **结构化表格** (`<table>`) | 表头自动添加浅灰背景，列宽自适应，单元格富文本对齐 |
| **☑️ 待办事项 (`to_do`)** | **任务勾选框** (`<checkbox done="false">`) | 原生支持飞书端打勾检核与状态同步 |
| **⏱️ 时间标签** | **紫色时间微徽章** | 自动识别 `5 分钟`、`10 分钟` 等时间标记并高亮呈现 |
| **📐 数学公式 (`equation`)** | **LaTeX 渲染** (`<latex>`) | 原生渲染数学公式与符号表达式 |
| **👤 文档权限** | **自动授予可管理权限** | 文档创建后自动为当前 CLI 账号赋予 `full_access`（可管理）权限 |

---

## 🚀 快速一键同步指令

直接在终端执行同步脚本：

```bash
node ~/.gemini/config/skills/notion-to-feishu/scripts/sync.mjs "<notion-url-or-id>"
```

### 可选参数：
- `--doc "<飞书文档链接或ID>"`：指定要覆盖更新的已有飞书云文档（如不提供则默认新建文档）。
- `--title "<自定义文档标题>"`：手动覆盖文档标题（默认自动提取 Notion 页面标题）。
- `--work-dir "<本地缓存目录>"`：指定临时生成的 XML 存放路径（默认 `./.notion_to_feishu_tmp`，执行完毕自动清理）。

### 执行示例：
```bash
# 直接使用 Notion 页面链接新建飞书文档
node ~/.gemini/config/skills/notion-to-feishu/scripts/sync.mjs "https://app.notion.com/p/f148002/01-AI-WorkBuddy-ea61d340a1c44c1fa2414245b16403aa"

# 同步并覆盖更新已有的飞书云文档
node ~/.gemini/config/skills/notion-to-feishu/scripts/sync.mjs "ea61d340a1c44c1fa2414245b16403aa" --doc "https://a1qr0odzabr.feishu.cn/docx/EPWodmmw1oWMbgxsP9XcrfGMnCh"

# 使用 32 位 Page ID 并自定义标题
node ~/.gemini/config/skills/notion-to-feishu/scripts/sync.mjs "ea61d340a1c44c1fa2414245b16403aa" --title "第 01 课｜AI 赋能认知与 WorkBuddy 全景"
```

---

## 🏗️ 架构与底层流程

```mermaid
flowchart LR
    A["Notion API<br>递归抓取 Block AST"] --> B["AST 转 XML 引擎<br>notion_ast_to_feishu_xml.mjs"]
    B --> C["lark-cli docs +create<br>创建飞书原生 Docx"]
    C --> D["API 激活折叠状态<br>PATCH update_text_style"]
    D --> E["生成完成<br>full_access 权限就绪"]
```

1. **Notion AST 递归抓取**：通过 `@notionhq/client` 深度遍历子块层级，获取完整丰富的 AST 树与富文本元数据。
2. **高保真 XML 转换**：`notion_ast_to_feishu_xml.mjs` 将 AST 节点精确映射为飞书 Docx XML（涵盖 Callout 主题配色、胶囊标签、栅格分栏、Mermaid 画板）。
3. **飞书 Docx 原生创建**：调用 `lark-cli docs +create --api-version v2 --as bot --doc-format xml` 渲染文档。
4. **原生 Toggle 状态激活**：遍历文档中包含子块的标题 block，调用 OpenAPI 写入 `style.folded: true`，实现默认折叠收起。

---

## 🔧 常见问题与排障

1. **Notion API 提示 Unauthorized 或 404**：
   - 确保目标 Notion 页面右上角菜单（`...`）已点击 **Connect to** 并授权了对应的 Notion Integration。
   - 检查环境变量 `NOTION_TOKEN` / `NOTION_API_KEY` 或 macOS Keychain 中的 `NOTION_TOKEN` 是否有效。
2. **飞书鉴权说明**：
   - 脚本默认使用 Bot 身份（`--as bot`）创建文档，并自动为当前 CLI 登录用户授权 `full_access` 权限，无需频繁手动重登。
