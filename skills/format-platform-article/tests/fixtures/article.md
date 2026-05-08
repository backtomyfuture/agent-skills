# 多平台发布测试文章

这是一段开场文字，用来验证微信公众号杂志专栏风的正文节奏。

![本地图片](./media/sample.png)

## 核心结论

> 好的发布包应该先保证结构稳定，再考虑自动发布。

| 平台 | 首版策略 | 风险 |
| --- | --- | --- |
| 微信公众号 | 内联样式 HTML | 图片上传 |
| 知乎 | 保守 Markdown | HTML 清洗 |
| 今日头条 | 弱样式 Markdown | 表格渲染 |

```bash
python3 scripts/build_publish_package.py article.md --output article.publish
```

远程图片会被保留并进入报告：

![远程图片](https://example.com/remote.png)
