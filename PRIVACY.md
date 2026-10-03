# 隐私与脱敏说明

这个目录是独立的公开发布副本。复制采用明确的文件清单，不会把原项目的整个目录递归带入。

## 已处理

| 来源 | 处理方式 |
| --- | --- |
| `inventory.db` 与 `Backups/` | 不复制；它们可能含真实库存、供应商、备注和流水。 |
| 原有的 `test.xlsx`、`拣货单.xlsx` 与 `example_bom.xlsx` | 不复制；示例 BOM 使用匿名的虚构记录重新生成，文件作者元数据设为 `Inventory System Demo`。 |
| `test_reports/`、`__pycache__/`、`.vscode/` | 不复制；可能含本机路径、执行记录或个人设置。 |
| `config.ini`、`dist/`、`build/` | 不复制；配置包含本机数据目录，可执行文件及构建缓存不属于源码上传清单。 |
| 旧 `PROJECT_SUMMARY.md` | 不复制；其中有本机绝对路径与过时的运行命令。改用本目录的 README。 |
| 旧 `REQUIREMENTS.md` | 不复制；属于早期设计资料，不是运行软件必需文件。 |
| 测试说明中的本机绝对路径 | 改成相对报告路径。 |

源码包含通用的 Windows 系统字体候选路径（`C:/Windows/Fonts`），它们不指向个人目录。虚构物料及库位记录仅位于 `tests/demo_fixtures.py`，供临时数据库测试使用，不来自本机库存数据库；正式程序首次建库不导入这些记录。

## 上传前核查

1. 在本目录运行 `python audit_public_bundle.py`，确认文件清单和文本/Excel 扫描通过。
2. 如果在本目录运行过应用或测试，确认 `inventory.db`、`Backups/`、`config.ini`、`test_reports/`、`dist/` 和导出文件没有被加入 Git。
3. 若后来添加截图、配置、日志或新示例文件，单独检查其中的账号、路径、联系人、密钥、业务数据和文档元数据。

本次脱敏针对当前清单中的文件。后续新增文件仍需重新审核。
