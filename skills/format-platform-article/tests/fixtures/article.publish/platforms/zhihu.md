这是一段开场文字，用来验证微信公众号杂志专栏风的正文节奏。

![本地图片](https://cdn.jsdelivr.net/gh/backtomyfuture/images@_md2zhihu_articlepublish_770d713a/.zhihu-src/de318da2caf8cdb9-sample.png)

## 核心结论

> 好的发布包应该先保证结构稳定，再考虑自动发布。


<table>
<tr>
<th>平台</th>
<th>首版策略</th>
<th>风险</th>
</tr>
<tr>
<td>微信公众号</td>
<td>内联样式 HTML</td>
<td>图片上传</td>
</tr>
<tr>
<td>知乎</td>
<td>保守 Markdown</td>
<td>HTML 清洗</td>
</tr>
<tr>
<td>今日头条</td>
<td>弱样式 Markdown</td>
<td>表格渲染</td>
</tr>
</table>

```bash
python3 scripts/build_publish_package.py article.md --output article.publish
```

远程图片会被保留并进入报告：

![远程图片](https://example.com/remote.png)



Reference:

