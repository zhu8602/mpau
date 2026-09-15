# Installation

## Windows installer (end users, no Python required)

Download `mpau-setup-<version>.exe` and run it. The installer:

- installs to `%LOCALAPPDATA%\Programs\mpau` (no admin rights needed)
- bundles the Python runtime and all browser drivers (patchright + playwright) — zero prerequisites
- extracts browser drivers to `%LOCALAPPDATA%\ms-playwright`
- stores runtime data (cookies, database, logs) in `%LOCALAPPDATA%\mpau-data` (override with `MPAU_HOME`)
- offers a desktop shortcut and optional auto-start on login; launches the app and opens the browser right after install

Browser resolution order: `MPAU_CHROME_PATH` > system Chrome > bundled Chromium, so machines without Chrome still work.

The installer is not code-signed; Windows SmartScreen will warn — choose "Run anyway".

### Building the installer

```bash
uv run python tools/build_installer.py                            # full build
uv run python tools/build_installer.py --skip-pip --skip-kernels  # incremental rebuild
```

Output: `package/dist/mpau-setup-<version>.exe`. Portable Inno Setup is fetched automatically on first build (`MPAU_INNO_URL` overrides the download mirror, `MPAU_ISCC` points at an existing ISCC.exe).

## Requirements

- Python `>=3.10,<3.13`
- Google Chrome
- `uv` is recommended
- `patchright` browser runtime
- `playwright` browser runtime for Baijiahao / TikTok legacy flows

## Install with uv

```bash
git clone https://github.com/cjccd/multi-platform-auto-upload.git
cd multi-platform-auto-upload

uv venv
source .venv/bin/activate
uv pip install -e .
```

Windows PowerShell:

```powershell
uv venv
.venv\Scripts\activate
uv pip install -e .
```

## Install without uv

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

## Browser runtimes

```bash
python -m patchright install chromium
python -m playwright install chromium
```

For slower networks:

```bash
PLAYWRIGHT_DOWNLOAD_HOST="https://npmmirror.com/mirrors/playwright" python -m patchright install chromium
PLAYWRIGHT_DOWNLOAD_HOST="https://npmmirror.com/mirrors/playwright" python -m playwright install chromium
```

## Optional runtime configuration

No config file is required by default. Use environment variables when you need to override runtime behavior:

```bash
export MPAU_CHROME_PATH="/path/to/chrome"
export MPAU_HEADLESS="true"
export MPAU_DEBUG="true"
```
