# Development

## Run tests

```bash
python3 -m unittest -v tests.test_mpau_cli
# 或全量(Web 测试需要 flask):
.venv/Scripts/python -m pytest tests/ -q
```

## Web frontend (web/ui)

新版管理后台是 Vue 3 SPA(`web/ui/`, Vue 3 + TS + Vite + Pinia + Element Plus + ECharts),
Flask 只提供 REST API 并托管 `web/ui/dist`(不存在时回退旧版 `templates/index.html`, 旧版也可从 `/legacy` 访问)。

```bash
# 开发: 后端 8898 + 前端 5173(vite proxy 代理 /api、/qrcodes、/package)
uv run --extra web python web/app.py
cd web/ui && pnpm install && pnpm dev

# 类型检查与构建
cd web/ui && npx vue-tsc --noEmit -p tsconfig.app.json && pnpm build
```

## Verify CLI help

```bash
python3 mpau_cli.py --help
python3 mpau_cli.py douyin --help
python3 mpau_cli.py pdd --help
python3 mpau_cli.py tiktok --help
```

## Before publishing a fork

Make sure you do not publish local runtime data:

- no `cookies/`
- no `logs/`
- no real video files
- no `.venv/`
- no `__pycache__/`
- no QR code images
- no personal account or shop credentials
