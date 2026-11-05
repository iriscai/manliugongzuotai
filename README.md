# 漫流工作台

Windows 桌面素材处理工作台，当前版本 **V0.26.1**。使用 Electron 界面、Python 本机服务和 SQLite 数据库，完成以下流程：

**导入素材 → 获取正文 → 标题及正文去重验收 → 按赛道提炼主题 → 改写生文与评分 → 推送生图工具标题库。**

## 本机迁移位置（2026-11-04）

正式程序：`E:\漫流工作台\版本\V0.26.1\漫画文章工作台.exe`。正式数据库：`E:\漫流工作台\程序\data\workbench.sqlite3`。源码及 Git：`E:\漫流工作台\项目\desktop-workbench`。桌面原快捷方式已切换到 E 盘。源码和会话的旧路径保留兼容链接；旧版桌面目录已移除，历史抓取路径已迁到 E 盘。

当前 V0.26.1 包含军事 C–G 多版本及个人 IP 自然口述修订；源码仓库为 [iriscai/manliugongzuotai](https://github.com/iriscai/manliugongzuotai)，运行数据保留本机。完整迁移校验记录在 `E:\漫流工作台\迁移记录`。

## 功能

- 素材库、种子、成品、任务与推送回执使用 SQLite 存储，支持检索、筛选、排序、赛道分布和处理节点定位。
- 对接外部正文抓取工具，支持条数、正文长度、浏览器并发、暂停和继续配置。
- 提炼支持 `1 → 1` 原赛道模式和 `1 → N` 多适配赛道模式，可全局配置并按任务覆盖。
- 生文可选择本机已登录的 Codex 或兼容中转 API，支持并发、预算、执行记录及失败任务重试。
- 搞笑 I/J 在一次模型响应中完成多阶段稿件修订、T1/T2 标题处理和评分；军事 C–G 各自提炼、初稿与局部自改，C/D/E 正文400–600字，F/G保留各版篇幅。
- API 临时故障有限重试，额度不足暂停；辅助字段兼容修复保留真实内容校验，合格的已保存失败响应可在匹配条件后复用。
- 结果库支持跨页勾选待评/失败稿件独立重新评分，保留原稿，支持并发、暂停继续、失败重试与调用用量记录。
- 成品按赛道与评分分流推送，记录接收回执和重试状态；支持归档、删除恢复和历史执行记录清理。

## 源码运行

运行环境为 Windows、Python 3.11 或以上、Node.js/npm。项目使用的 Electron 版本为 `31.7.7`。以下命令在项目根目录的 PowerShell 中执行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
npm install

$env:COMIC_PYTHON = (Resolve-Path '.\.venv\Scripts\python.exe').Path
$env:COMIC_DATA_DIR = Join-Path (Get-Location).Path 'data'
Remove-Item Env:ELECTRON_RUN_AS_NODE -ErrorAction SilentlyContinue
npm start
```

首次运行创建本机数据库并加载 `resources/` 中的规则资源。仓库不携带生产数据库、账号密钥、浏览器登录状态或业务执行响应。

启动后在界面配置执行方式、正文抓取工具和推送目标路径。API Key 在 Windows 上通过 DPAPI 加密保存，不应提交至 Git。

### 外部能力

| 能力 | 依赖与配置 |
| --- | --- |
| Codex 提炼/生文 | 本机安装并登录 Codex，必要时在设置中填写程序路径、模型及推理强度。 |
| 中转 API 提炼/生文 | 在设置中填写接口地址、模型、协议及密钥。连接测试会发送请求，生文按接口计费。 |
| 正文抓取 | 外部 `ArticleBodyScraper` 文件模式工具；在界面选择对应可执行文件。该项目未包含在本仓库。 |
| 生图工具推送 | 外部 `ReferenceImageBatchFactory` 接收端；配置实际目标项目并确认接收端正常运行。该项目未包含在本仓库。 |

代码保留了原开发机的一些默认路径。在其他机器上应使用界面配置或环境变量覆盖，勿把默认路径当作已安装依赖。

### 环境变量

| 变量 | 用途 |
| --- | --- |
| `COMIC_PYTHON` | 源码运行时使用的 Python 可执行文件绝对路径。 |
| `COMIC_DATA_DIR` | 独立数据目录；测试和开发应与正式库隔离。 |
| `COMIC_PUSH_TARGET_PROJECT` | 覆盖推送目标项目路径，测试时使用隔离目标。 |

## 项目结构

```text
main.js / preload.js   Electron 主进程和界面桥接
renderer/              工作台界面
backend/               本机 HTTP 服务、SQLite、任务、提炼、生文及推送
resources/             赛道、提示词及搞笑版本验收资源
assets/                应用图标
tests/                 回归检查及本机测试服务
build_backend.py       Python 后端冻结构建入口
build_portable.py      原开发机历史便携包构建脚本
```

`resources/` 的版本验收资源属于程序规则的一部分，予以保留。`data/`、`outputs/`、`build/`、第三方安装目录和可执行文件由 `.gitignore` 排除。

## 验证与构建

在准备好 Python 环境后，可运行不调用付费模型的隔离回归检查：

```powershell
.\.venv\Scripts\python.exe -X utf8 tests/bulk_score_checks.py
.\.venv\Scripts\python.exe -X utf8 tests/score_schema_checks.py
.\.venv\Scripts\python.exe -X utf8 tests/api_transport_checks.py
.\.venv\Scripts\python.exe -X utf8 tests/task_pause_checks.py
.\.venv\Scripts\python.exe -X utf8 tests/extraction_modes_checks.py
.\.venv\Scripts\python.exe -X utf8 tests/usability_checks.py
```

部分历史测试依赖本机 `outputs/` 的验收语料、外部工具、固定路径或 Playwright 环境，不能在全新克隆后直接运行所有测试。名称带 `live`、`production` 或 `installed` 的测试可能连接真实配置，执行前先查看其用途。上述列出的隔离检查使用本机测试服务或模拟模型。

冻结后端：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
.\.venv\Scripts\python.exe -X utf8 build_backend.py
```

输出为 `build/backend/comic-backend.exe`。`build_portable.py` 保留原开发机历史发布逻辑及固定路径，不能直接用于其他机器，也不要在生产任务运行时直接执行。源码运行不需要该脚本。

## 使用说明

- [完整使用说明](使用说明.md)
- [素材处理节点说明](素材处理节点说明.md)
- [单次多赛道提炼说明](单次多赛道提炼说明.md)
- [API 接入说明](API接入说明.md)

本仓库保存应用源码和随应用分发的规则，不自动包含本机独立安装的其他 SKILL 或外部项目。
