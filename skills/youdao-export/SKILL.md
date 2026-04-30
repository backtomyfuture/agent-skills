---
name: youdao-export
description: >
  Export all files from Youdao Cloud Notes (有道云笔记) to local filesystem,
  preserving original folder structure. Supports ALL file types: notes (exported as .docx),
  Word attachments, PDF, Excel, PPT. Includes post-download verification.
  Use when the user wants to export, backup, or download from Youdao Cloud Notes.
  Triggers on: "导出有道云笔记", "备份有道云", "youdao export", "下载有道云笔记",
  "有道云笔记迁移", or any task involving Youdao Cloud Notes data export.
---

# 有道云笔记全量导出

将有道云笔记网页版的所有文件（笔记、Word、PDF、Excel、PPT）导出到本地，保持原始文件夹结构。

## 前置条件

- chrome-cdp skill 已安装
- Chrome 远程调试已开启（`chrome://inspect/#remote-debugging`）

## 工作流程（5 步）

### 第 1 步：打开网站并登录

1. 使用 chrome-cdp 的 `scripts/cdp.mjs list` 查看是否已有有道云笔记 tab
2. 如果没有，提示用户在 Chrome 中打开 `https://note.youdao.com/web` 并登录
3. 等用户确认已登录后，获取 target ID

```bash
node <chrome-cdp>/scripts/cdp.mjs list
# 找到 note.youdao.com 对应的 target ID（如 B1E49379）
```

### 第 2 步：确认下载目录

询问用户指定本地输出目录（默认 `~/Downloads/youdao-export`），然后：

1. 创建临时下载目录用于 Chrome 下载中转：`<outputDir>/.downloads`
2. 通过 CDP 设置 Chrome 下载路径（**关键**，避免沙箱权限问题）：

```javascript
// 使用 cdp.mjs evalraw 调用 Page.setDownloadBehavior
cdpEvalRaw("Page.setDownloadBehavior", { behavior: "allow", downloadPath: tempDlDir })
```

### 第 3 步：遍历并下载所有文件

执行 `scripts/export-all.mjs`，核心逻辑：

#### 3a. 获取文件夹树

**关键经验**：
- 使用 `[id^="filenode-"]` 选择器（**不是** `[id^="filenode-WEB"]`），因为有些文件夹是 `filenode-SVR` 开头
- 用 `e.style.paddingLeft`（**内联 style**）获取缩进深度，**不是** `getComputedStyle`
- pl=12 是顶级，pl=24 是二级，pl=36 是三级
- 有道云笔记使用虚拟列表，**每次点击文件夹前必须重新获取节点列表**（通过名称匹配找到当前 ID）

```javascript
// 正确获取文件夹树
const raw = cdpEval(`JSON.stringify([...document.querySelectorAll('[id^="filenode-"]')].map(function(e){
  var pl = parseInt(e.style.paddingLeft) || 0;
  var nameEl = e.querySelector('.file-name');
  var name = nameEl ? nameEl.textContent.trim() : e.textContent.trim().split('\\n')[0].trim();
  return { id: e.id, name: name, pl: pl };
}))`);
```

#### 3b. 构建路径树

```javascript
const stack = [];
for (const f of allFolders) {
  while (stack.length > 0 && stack[stack.length - 1].pl >= f.pl) stack.pop();
  const parent = stack.length > 0 ? stack[stack.length - 1].path : "";
  f.path = parent ? parent + "/" + f.name : f.name;
  stack.push({ pl: f.pl, path: f.path });
}
```

#### 3c. 逐文件夹下载

对每个文件夹：

1. **重新获取节点列表**，通过名称找到当前 ID（虚拟列表可能重排）
2. 点击文件夹，等待 1.5-2 秒
3. 获取文件列表，**排除子文件夹**：
   ```javascript
   // type_folder 是子文件夹，过滤掉
   .filter(x => x.type !== '#type_folder')
   ```
4. 根据文件类型选择下载方式：

| 文件类型（xlink:href） | 下载方式 |
|------------------------|----------|
| `#type_note` | 点击文件 → 显示 `.widget-menu` → 点击"导出为Word" |
| `#type_word` / `#type_pdf` / `#type_excel` / `#type_ppt` | 点击文件 → 显示 `.widget-menu` → 点击"下载" |

**下载操作的关键步骤**：

```javascript
// 1. 点击文件项打开预览
document.querySelectorAll('.list-li.file-item')[index].click()
// 等待 2 秒

// 2. 强制显示工具栏菜单（有道云用 JS 控制显隐）
var ul = document.querySelector('.widget-menu');
if (ul) { ul.style.display='block'; ul.style.visibility='visible'; ul.style.opacity='1'; }
// 等待 0.5 秒

// 3. 点击菜单项
var items = document.querySelectorAll('.widget-menu .toolbar-menu-item');
for (var i = 0; i < items.length; i++) {
  var t = items[i].textContent.trim();
  if (t === '导出为Word' || t === '下载') { items[i].click(); break; }
}
```

5. 在临时下载目录检测新文件（轮询，忽略 `.crdownload` 和 `.tmp`）
6. 移动到正确的本地文件夹

### 第 4 步：验证

执行 `scripts/verify.mjs`，核心逻辑：

1. 重新获取网页文件夹树（同第 3 步方法）
2. 逐文件夹对比网页文件列表与本地文件
3. 匹配时注意：
   - 笔记导出后文件名可能被截断（有道云导出 Word 时会截断长标题）
   - 用前 18 个字符做模糊匹配
   - 忽略 Chrome 添加的 `(1)` `(2)` 后缀

### 第 5 步：统计报告

输出：
- 网页文件总数 / 本地文件总数
- 网页文件夹数 / 本地文件夹数
- 缺失文件列表（如有）
- 多余文件列表（如有）
- 下载成功/失败/跳过数量

## 脚本说明

| 脚本 | 用途 |
|------|------|
| `scripts/export-all.mjs` | 主脚本：遍历所有文件夹，下载所有文件 |
| `scripts/verify.mjs` | 验证：逐文件夹对比网页与本地 |

## 已知问题与应对

1. **虚拟列表跳位**：有道云笔记左侧树使用虚拟列表，点击操作后节点 ID 可能变化。解决：每次点击前重新获取节点列表
2. **`(1)` `(2)` 后缀**：Chrome 对同名文件自动加后缀。解决：下载完成后统一重命名
3. **"导出为Word"下载位置不受 `Page.setDownloadBehavior` 控制**：部分笔记的 Word 导出会下载到 `~/Downloads`。解决：同时监控两个目录
4. **文件名中含 `.` 导致匹配误判**：如 `V1.0.docx`，normalize 会错误截断。解决：用前缀匹配而非精确匹配
