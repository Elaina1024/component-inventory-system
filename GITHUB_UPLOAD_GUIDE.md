# GitHub 上传说明

只把**本目录 `github_upload` 的内容**作为仓库根目录。上一级原项目目录包含实际数据库和备份，不应整体上传。

上传前先运行：

```powershell
python audit_public_bundle.py
```

然后在本目录初始化 Git，检查暂存清单：

```powershell
git init
git add .
git status --short
git diff --cached --name-only
```

暂存清单中应只有源码、打包脚本、测试、四个 SVG 箭头、匿名 `example_bom.xlsx`、依赖文件和说明文档。不应出现 `inventory.db`、`Backups/`、`test_reports/`、`config.ini`、构建产物或其他 Excel 文件。

确认后，在 GitHub 上创建仓库，再使用该仓库提供的远程地址提交和推送。当前目录没有自动连接 GitHub，也没有替你选择公开/私有权限或许可证。
