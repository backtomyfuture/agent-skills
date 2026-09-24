---
name: kaoqin
description: 月度绩效考核自动化工具。汇总飞书周报与任务拆解生成 G2 开发工作量、G3 测试工作量与 G4 自研项目类工作总结，查询海航 OA 休假记录生成 G7 出勤情况，并通过 ego-browser 填写金山绩效考核表的“架构师（傅强）”工作表，自动补齐考核分值与完成情况，同时保留原表格公式和样式。
---

# 月度绩效考核

本 Skill 用于完成研发中心的月度绩效考核自动化填报。它从飞书多维表格提取当月工作计划与任务拆解，分别归纳提炼生成 **G2 开发工作量**、**G3 测试工作量** 以及 **G4 自研项目类工作** 总结；从海航 OA 查询当月审批通过的休假记录，生成 **G7 出勤情况**；最后驱动 `ego-browser` 将考核分值和完成情况无损填入金山绩效考核表。

---

## 目标系统与数据源配置

### 1. 飞书多维表格（G2 / G3 / G4 工作量数据源）
| 配置项 | 值 |
| --- | --- |
| **Base 链接** | `https://a1qr0odzabr.feishu.cn/base/IWRrbFNSXaF6ORsm7qtcUSARnie` |
| **Base Token** | `IWRrbFNSXaF6ORsm7qtcUSARnie` |
| **主表（周度工作计划）** | `tblTvWzgpmXCb0VQ` |
| **关联表（项目任务拆解表）** | `tbldvNyijOFzXzbe` |
| **默认人员** | 傅强 (`ou_538a14647caf5eef00523c50e7d76521`) |

### 2. 海航OA系统（G7 考勤数据源）
| 配置项 | 说明 |
| --- | --- |
| **查询接口** | `opencli hnaoa`（我呈报的公文 / HRM休假申请） |
| **解析内容** | 提取当月审批通过的年休假、倒休、事假、病假等休假记录与天数 |

### 3. 金山表格（绩效填报目标）
| 配置项 | 值 |
| --- | --- |
| **文档链接** | `https://www.kdocs.cn/l/cinpHQZ2n43a` |
| **唯一限定工作表** | **“架构师（傅强）”**（严禁修改其他工作表） |

---

## 完整执行流程

### 第一步：提取当月周报并生成 G2、G3、G4 工作总结

执行内置的数据抓取与总结提炼脚本：

```bash
# 抓取指定月份的工作记录并生成 G2、G3、G4 总结（默认当前月，可传 --month 9 等）
python3 /Users/jarod/Documents/agent-skills/skills/kaoqin/scripts/fetch_and_summarize.py --month <月份>

# 仅输出 G2/G3/G4 总结文本块
python3 /Users/jarod/Documents/agent-skills/skills/kaoqin/scripts/fetch_and_summarize.py --month <月份> --summary-only

# 输出结构化 JSON
python3 /Users/jarod/Documents/agent-skills/skills/kaoqin/scripts/fetch_and_summarize.py --month <月份> --json
```

#### 工作内容分类与提炼规则

1. **G2 开发工作量 (60%) 提炼规则**：
   - 提取当月所有开发、技术交付与 AI 创新工作（涵盖所属系统、下周工作计划、完成情况说明及关联拆解任务）。
   - 按业务系统/技术模块归纳整理为标准的编号列表：
     ```text
     1. [系统/模块名称]：具体完成内容、核心推进进展与成果；
     2. [系统/模块名称]：具体完成内容、核心推进进展与成果；
     ...
     ```
2. **G3 测试工作量 (20%) 提炼规则**：
   - 对应绩效规则：`基准分95分，满分100分。得分=95+测试用例系统数量*用例数量系数*50%+内测系统数量*bug系数*50%`。
   - 优先提取周报中工作类型为测试、拆解任务为测试类/Bug修复类的条目，总结测试用例编写评审、测试实施、联调测试与缺陷修复情况。
   - 若当月无独立测试任务拆解条目，则提取当月负责的自研项目与自研工具（如邮箱cli工具、自动化报表与脚本等），总结其功能测试、联调验证及缺陷查找与修复情况（例如：`对自研的邮箱cli工具进行测试，查找问题并修复`）。
3. **G4 自研项目类工作 (20%) 提炼规则**：
   - 对应绩效规则：`基准分95分，满分100分。自研项目类工作打分：需求挖掘、调研 +2分/个；需求文档及确认 +3分/个；项目跟进 +3分/个`。
   - 提取周报中需求调研、需求文档编写、业务沟通与项目跟进的自研工作条目，按格式总结（例如：`[系统/项目名称]，与业务部门沟通，完成需求调研并编写需求文档与方案设计`）。

*若用户显式提供了 G2、G3 或 G4 的原文，则优先采用用户提供的原文。*

---

### 第二步：查询 OA 休假记录并生成 G7 出勤情况

执行内置的月度绩效考核出勤查询脚本：

```bash
# 查询指定月份的休假记录（默认当前月，可传 9 或 9月 等）
python3 /Users/jarod/Documents/agent-skills/skills/kaoqin/scripts/query_attendance.py <月份>
```

#### G7 文本生成规则
- 有休假时输出：`X月年休假N天，倒休M天；无异常出勤情况`（如 `8月年休假1天；无异常出勤情况`）
- 无休假时输出：`X月无休假；无异常出勤情况`
- 若用户显式指定了 G7 文本（如“全勤”、“出勤正常”等），则优先采用用户原文。

---

### 第三步：考核分值与填报项映射

填报时自动补齐以下默认分值与状态（仅在单元格为空或重置时写入）：

| 单元格 | 项目说明 | 默认填报得分 | 默认填报完成情况 |
| --- | --- | --- | --- |
| **E2** / **G2** | 开发工作量 (60%) | `100` | **第一步生成的 G2 开发工作量总结**（或用户提供原文） |
| **E3** / **G3** | 测试工作量 (20%) | `95` | **第一步生成的 G3 测试工作量总结**（或用户提供原文） |
| **E4** / **G4** | 自研项目类工作 (20%) | `95` | **第一步生成的 G4 自研项目类工作总结**（或用户提供原文） |
| **E5** / **G5** | 计划完成率 (25%) | `100` | `所有任务均按计划完成，完成率100%` |
| **E6** / **G6** | 系统可用性与合规性 (25%) | `100` | `本月不涉及` |
| **E7** / **G7** | 出勤 (30%) | `100` | **第二步获取的 G7 考勤总结**（或用户提供原文） |
| **E8:E12** / **G8:G12** | 行政秩序/纪律各项 | `100` | `本月合规` |
| **E13** / **G13** | 加减分项 (30%) | `100` | `本月无表彰` |
| **G14** | 综合评分说明 | 留空 | 留空 |

---

### 第四步：绩效考核表自动化填报与样式保护

使用 `ego-browser nodejs <<'EOF' ... EOF` 执行所有浏览器操作：

1. **禁止直接在单元格网格粘贴**，避免破坏原有字体（YaHei）、字号（10）和对齐样式。
2. **标准公式栏安全写入流程**：
   - 通过 Name Box 原生事件输入目标单元格坐标并按 `Enter` 选中单元格；
   - 触发 `Delete` 键清空当前单元格已有内容，防止追加字符污染；
   - 点击公式栏编辑区 (`[350, 95]`)；
   - 通过 `typeText` 写入新内容并按 `Enter` 提交。
3. **范围约束**：仅操作“架构师（傅强）”工作表的 E2:E13 及 G2:G14，绝不修改 F 列自动计算公式或其他工作表。

#### 自动化驱动脚本示例

```bash
ego-browser nodejs <<'EOF'
const task = await useOrCreateTaskSpace('kaoqin');
cliLog('Task space id: ' + task.id);

// 1. 打开目标金山表格
await openOrReuseTab('https://www.kdocs.cn/l/cinpHQZ2n43a', { wait: true, timeout: 20 });
await wait(3);

// 2. 确认工作表标签精确为“架构师（傅强）”
const shot = await captureScreenshot();
cliLog('Initial shot: ' + shot);

// 3. 定义高可靠单元格安全写入函数
async function setCell(cell, value) {
  // 通过 Name Box 切换定位
  await js(`(() => {
    const el = document.querySelector('.name-box input.edit-box');
    if (el) {
      el.focus();
      el.value = '${cell}';
      el.dispatchEvent(new Event('input', { bubbles: true }));
      el.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', keyCode: 13, which: 13, bubbles: true }));
    }
  })()`);
  await wait(0.2);

  // 清除旧内容
  await pressKey('Delete');
  await wait(0.15);

  // 点击公式栏并写入新内容
  await click([350, 95]);
  await wait(0.15);
  await typeText(value);
  await wait(0.15);
  await pressKey('Enter');
  await wait(0.25);
}

// 4. 依次写入分值与完成情况
await setCell('E2', '100');
await setCell('G2', `<第一步生成的G2开发工作量总结>`);

await setCell('E3', '95');
await setCell('G3', `<第一步生成的G3测试工作量总结>`);

await setCell('E4', '95');
await setCell('G4', `<第一步生成的G4自研项目类工作总结>`);

await setCell('E5', '100');
await setCell('G5', '所有任务均按计划完成，完成率100%');
await setCell('E6', '100');
await setCell('G6', '本月不涉及');

await setCell('E7', '100');
await setCell('G7', `<第二步获取的G7出勤情况>`);

await setCell('E8', '100');
await setCell('G8', '本月合规');
await setCell('E9', '100');
await setCell('G9', '本月合规');
await setCell('E10', '100');
await setCell('G10', '本月合规');
await setCell('E11', '100');
await setCell('G11', '本月合规');
await setCell('E12', '100');
await setCell('G12', '本月合规');
await setCell('E13', '100');
await setCell('G13', '本月无表彰');

// 5. 截图校验
const finalShot = await captureScreenshot();
cliLog('Final shot: ' + finalShot);
EOF
```

---

## 验收与自检清单

1. **G2 / G3 / G4 考核内容完整性**：
   - **G2** 准确涵盖当月负责的自研项目核心开发交付、AI 创新工作及技术赋能（编号列表）；
   - **G3** 准确提炼当月系统测试、测试用例编写评审、缺陷排查修复或自研工具功能测试情况；
   - **G4** 准确涵盖当月自研项目的需求调研、需求文档确认、业务沟通与项目跟进推进情况。
2. **G7 出勤数据真实性**：G7 与 OA 请假公文真实审批情况完全一致。
3. **工作表严格隔离**：修改前后均保持在“架构师（傅强）”工作表，未触碰其他员工表格。
4. **加权公式联动**：F 列加权得分与总分自动计算正常，未被覆盖。
5. **格式与样式保真**：所有填入单元格字体、对齐和换行排版正常。
6. **任务收尾**：填报并截图核对无误后，调用 `completeTaskSpace(task.id, { keep: false })` 清理或按用户需求保留页面。
