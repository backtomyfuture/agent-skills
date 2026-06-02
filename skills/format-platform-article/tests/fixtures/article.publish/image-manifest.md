# 多平台发布测试文章 图片上传清单

非知乎平台的主 HTML 会尽量内嵌本地图片。
知乎通过 md2zhihu 生成 `platforms/zhihu.md`，图片由 Git 图床托管为 HTTPS 链接。如果未配置 `--zhihu-asset-repo` 或未安装 md2zhihu，`zhihu.md` 会使用本地 `../assets/` 链接，请按下列顺序从 `assets/` 手工补图。

1. 本地图片
   - 文件：`assets/sample.png`
2. 核心结论
   - 文件：`assets/tables/table_01_核心结论.png`
3. 远程图片
   - 文件：`https://example.com/remote.png`
