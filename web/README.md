# mpau Web 管理后台

在 [multi-platform-auto-upload](../README.zh-CN.md) 之上包一层网页界面:
**账号管理(扫码登录) + AI 文案引擎 + 上传任务队列(后台执行, SQLite 持久化) + 批量发布编排**。

## 前端架构(Vue 3 SPA)

- `ui/`: 新版前端工程(Vue 3 + TypeScript + Vite + Pinia + Vue Router + Element Plus dark + ECharts)
- `templates/index.html`: 旧版单文件前端, 保留为 `/legacy` 应急回退(稳定后移除)
- 路由规则(`web/app.py`): `ui/dist` 存在时 `GET /` 托管新 SPA(含前端路由 fallback); 否则回退旧版模板

### 开发

```powershell
# 终端 1: 后端 API(8898)
uv run --extra web python web/app.py
# 终端 2: 前端热更新(5173, /api 等已代理到 8898)
cd web/ui; pnpm install; pnpm dev
```

### 构建部署

```powershell
cd web/ui; pnpm build   # 输出 web/ui/dist, Flask 自动托管, 无需重启策略变化
```

类型检查: `cd web/ui; npx vue-tsc --noEmit -p tsconfig.app.json`

## 启动

```powershell
cd D:\dsh\multi-platform-auto-upload
uv run --extra web python web/app.py
```

打开启动输出中带 `?token=` 的完整链接(或打开 <http://127.0.0.1:8898> 后在登录页输入令牌, 令牌见 `data\web_token.txt`)。

### 局域网模式(局域网内用户可访问)

```powershell
powershell -ExecutionPolicy Bypass -File web\start-lan.ps1
```

脚本会自动: 以 `0.0.0.0` 启动 + 添加 Windows 防火墙入站规则(端口 8898) + 打印局域网地址。

手动方式:

```powershell
$env:MPAU_WEB_HOST = "0.0.0.0"   # 或 MPAU_WEB_HOST=0.0.0.0
uv run --extra web python web/app.py
# 防火墙: netsh advfirewall firewall add rule name="mpau-web-8898" dir=in action=allow protocol=TCP localport=8898
```

局域网访问地址: `http://<本机局域网IP>:8898`(查看 IP: `ipconfig` 或 `Get-NetIPAddress`)

⚠️ 局域网模式同样需要访问令牌(启动输出中带 `?token=` 的完整链接); 令牌等同账号控制权, 请勿外发, 不要暴露公网。

环境变量(可选):

| 变量 | 默认 | 说明 |
|---|---|---|
| `MPAU_WEB_PORT` | `8898` | 端口 |
| `MPAU_WEB_HOST` | `127.0.0.1` | 绑定地址; 设 `0.0.0.0` 为局域网模式(仍需令牌) |
| `MPAU_WEB_TOKEN` | 自动生成 | 访问令牌, 默认写入 `data\web_token.txt`; 设此变量可固定令牌 |
| `MPAU_WEB_FILES_ROOT` | `D:\videos` | 文件浏览默认目录 |
| `MPAU_DATA_DIR` | `<项目根>\data` | SQLite/配置目录(测试隔离用) |

## 使用流程

1. **账号中心**(批量发布页顶部): 每平台「＋ 登录」→ 扫码登录(可多账号并存):
   - 有头模式: 本机弹出浏览器, 手机 App 扫码
   - 无头模式(服务器): 登录弹窗内直接展示该账号二维码(多账号并发登录互不干扰), 失败时弹窗内嵌任务日志可查原因
   - 账号「管理」菜单: ✓检查登录状态 / ↪退出登录 / 📋查看任务日志
2. **等登录任务完成**(任务状态变 `success`), 账号出现在该平台的多选下拉中
3. **发布(统一走「📦 批量发布」)**: 单条发布已并入批量发布(单条 = 只有 1 条视频的批次), 两种入料方式:
   - **扫描文件夹 / 导入 CSV**(每视频一行): 整批进入, 批次下拉可切换
   - **🎬 选择单条视频**: 文件浏览器选 1 个视频 → 无批次自动新建单条批次, 已有批次则追加去重; 选完即作为批次内普通视频, **完全沿用批量视频的操作逻辑**(无专属表单)
   - **多账号多样发布**: 账号映射每平台可多选账号(默认全选), 条目按 视频×平台×账号 展开, 同平台多账号自动生成差异化标题
   - 统一链路: 填 AI 提示词(可选, 也可用 sidecar/CSV 给单条视频带人工标题)→ ✨一键生成全部文案 → 审阅表格(预览/编辑/重新生成/批准)→ ✅全部排队 → 🚀一键发布 → 导出报告
4. **任务队列**(右侧栏)实时显示登录/发布/批量任务状态; 打开日志抽屉查看逐行日志; 抖音触发短信验证时出验证码输入框
5. **设置**(顶栏 ⚙️): 配 LLM(OpenAI 兼容接口, 推荐 DeepSeek)与风控(条间间隔/每日上限)

## AI 文案与批量(架构)

- 代码: `pipeline/` 包(store/copy_engine/planner/scanner/scheduler/batch_runner), Web 与 CLI(`mpau batch ...`)共用
- 数据: `data/mpau.db`(任务/视频/条目/防重发/设置)+ `data/config.json`(LLM Key, 本机私有, gitignore)
- CSV 格式(每视频一行): 文件名,人工标题,描述,标签,定时发布时间,封面路径,商品链接,商品短标题,商品ID
  (快手挂车用**商品名称**,请在条目编辑器里填,CSV 的商品ID 列对快手无效)
- 校验: 抖音≤55字 / 快手≤55字 / 小红书≤20字(硬性)+ 极限词提示 / 视频号短标题≤16字 / 京东5-27字 / 天猫≤30字
- 风控: 同一「平台+账号」串行、跨平台账号并发(默认上限 4), 条间间隔默认 5 分钟, 每账号日上限默认 25, sha256+平台+账号 防重发

## 平台能力对照(与 CLI 一致)

| 平台 | 视频 | 图文 | 定时 | 挂商品 | 试跑 |
|---|---|---|---|---|---|
| 抖音 `douyin` | ✅ | ✅ | ✅ | 商品链接 | `--dry-run` |
| 视频号 `tencent` | ✅ | ❌ | ✅ | 微信小店商品ID | 存草稿 |
| 快手 `kuaishou` | ✅ | ✅ | ✅ | **商品名称**(按名称搜索关联) | — |
| 小红书 `xiaohongshu` | ✅ | ✅ | ✅ | — | — |
| PDD `pdd` / 天猫 `tmall` / 京东 `jd` | ✅ | ❌ | ✅ | 商品ID | `--dry-run` |
| 百家号 `baijiahao` | ✅ | ❌ | ✅ | — | — |
| TikTok `tiktok` | ✅ | ❌ | ✅ | — | — |
| B站 `bilibili` | ✅ | ❌ | ✅ | — | — |

> Web 批量支持上表除 B站 外的全部平台(TikTok 在账号中心「更多平台」下; B站 走 CLI `mpau bilibili`, 需 `--tid` 分区)。

## API 一览

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/platforms` | 平台列表 |
| GET | `/api/accounts?platform=` | 某平台已登录账号 |
| POST | `/api/accounts/login` | 启动扫码登录任务 `{platform, account, headless}`(启动前自动清理旧二维码) |
| POST | `/api/accounts/check` | 检查 Cookie `{platform, account}` |
| POST | `/api/accounts/finish-login` | 手机端扫码确认后调用, 校验 Cookie 并结束登录任务 `{platform, account}` |
| POST | `/api/verify` | 提交短信验证码 `{platform, account, code}` |
| GET | `/api/qrcodes` | 最新登录二维码列表 |
| GET | `/qrcodes/<file>` | 二维码图片 |
| GET | `/api/drives` | 本机盘符列表(文件浏览切换盘符用) |
| GET | `/api/files?path=` | 目录浏览(支持 `E:`/`E:\` 盘符写法) |
| GET | `/api/tasks` | 任务列表(含日志, SQLite 持久化) |
| POST | `/api/tasks` | 创建发布任务 |
| POST | `/api/tasks/<id>/cancel` | 取消运行中任务 |
| GET | `/api/copy/rules` | 各平台文案规则(字数/违禁词) |
| POST | `/api/copy/generate` | AI 生成多平台文案 `{platforms,title,desc?,tags?,product_*,goods_id?,with_desc,with_tags}` |
| POST | `/api/copy/validate` | 校验单平台标题 `{platform,title}` |
| GET/POST | `/api/settings` | LLM 与风控配置(api_key 回传脱敏) |
| POST | `/api/batch/scan` | 扫描文件夹 `{dir,batch_id?}` |
| POST | `/api/batch/import` | 导入 CSV `{csv,batch_id?}` |
| POST | `/api/batch/videos/add` | 选择单条视频 `{path,batch_id?}`(无批次自动新建, 重复返回 `added:false`) |
| GET | `/api/batch/videos` / `.../csv` | 视频清单 / 导出清单 CSV |
| POST | `/api/batch/videos/<id>` | 更新视频人工标题等字段 |
| POST | `/api/batch/plan` | 视频×平台展开为条目 `{batch_id,video_ids?,platforms,accounts}` |
| POST | `/api/batch/generate` | 批量 AI 生成文案 `{batch_id,platforms?,with_desc,with_tags}` |
| GET | `/api/batch/items?batch_id=` | 条目列表(含候选文案) |
| POST | `/api/batch/items/<id>` | 更新条目文案/状态 |
| POST | `/api/batch/items/<id>/regenerate` | 单条重新生成 |
| POST | `/api/batch/items/<id>/retry` | 重试失败条目 |
| POST | `/api/batch/approve` | 批准条目 `{batch_id,item_ids?}` |
| POST | `/api/batch/run` | 启动限速发布 `{batch_id,interval_min,dry_run,draft,headless,force}` |
| POST | `/api/batch/stop` | 停止批次调度 |
| GET | `/api/batch/status?batch_id=` | 批次进度/条目状态 |
| GET | `/api/batch/batches` | 批次列表 |
| GET | `/api/batch/report?batch_id=` | 导出批次报告 CSV |

## 一键安装包(package/dist/, 给最终用户)

**推荐: Inno 安装版** — 单文件 `mpau-setup-<版本>.exe`(约 500MB), 双击即装:

- 免管理员, 装到 `%LOCALAPPDATA%\Programs\mpau`
- 内置 Python 运行时与全部浏览器内核(patchright + playwright), 用户零依赖
- 内核释放到 `%LOCALAPPDATA%\ms-playwright`; 运行数据(cookie/数据库/日志)在 `%LOCALAPPDATA%\mpau-data`(可用 `MPAU_HOME` 改)
- 可选桌面快捷方式 / 开机自启; 装完自动启动并打开浏览器(自动携带访问令牌)
- 浏览器三级策略: `MPAU_CHROME_PATH` > 系统 Chrome > 内置内核兜底(没装 Chrome 也能用)

构建(项目根目录, 需 .venv):

```bash
uv run python tools/build_installer.py                              # 完整构建(首次约 20~30 分钟)
uv run python tools/build_installer.py --skip-pip --skip-kernels    # 快速重建(复用依赖/内核, 约 15 分钟)
```

Inno Setup 缺失时自动下载便携版(可用 `MPAU_INNO_URL` 换镜像 / `MPAU_ISCC` 指定已有 ISCC)。注意: 安装包未做代码签名, 用户首次运行会看到 SmartScreen 提示(选"仍要运行")。

**旧渠道(保留, 不再推荐)**: `package/` 下的 `setup.bat` + `install.ps1` + `mpau.zip`(约 320MB, 用 `tools/build_package.py` 重建)。需要目标机联网装 Python/uv/内核, 故障面大, 仅作备用。

注意: install.ps1 必须保存为 **UTF-8 带 BOM**(Windows PowerShell 5.1 兼容中文)。

## 注意

- 任务与批量数据持久化在 `data/mpau.db`, 重启服务后自动恢复(`running`→`已中断`, 可重新批准续传)
- 发布是浏览器自动化, 有平台风控风险, 首次建议「试跑」模式 + 有头观察
- 默认仅本机访问(127.0.0.1)+ 令牌认证; 局域网模式也需令牌, 不要直接暴露公网
