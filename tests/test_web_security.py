# -*- coding: utf-8 -*-
"""Web 安全回归: 令牌认证 / 二维码白名单 / batch_id 校验 / LLM 试连 SSRF 防护。

注意: 必须在导入 web.app 之前设置 MPAU_DATA_DIR 隔离数据目录。
"""
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["MPAU_DATA_DIR"] = tempfile.mkdtemp(prefix="mpau-websec-test-")

from web import app as webapp  # noqa: E402


class WebAuthTests(unittest.TestCase):
    def setUp(self):
        self.client = webapp.app.test_client()
        self.token = webapp.web_token()

    def test_api_requires_token(self):
        resp = self.client.get("/api/tasks")
        self.assertEqual(resp.status_code, 401)

    def test_page_redirects_to_login(self):
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/login", resp.headers["Location"])

    def test_login_page_accessible_without_token(self):
        resp = self.client.get("/login")
        self.assertEqual(resp.status_code, 200)

    def test_wrong_token_rejected(self):
        resp = self.client.get("/api/tasks", headers={"X-MPAU-Token": "wrong-token"})
        self.assertEqual(resp.status_code, 401)

    def test_header_token_authorizes(self):
        resp = self.client.get("/api/tasks", headers={"X-MPAU-Token": self.token})
        self.assertEqual(resp.status_code, 200)

    def test_bearer_token_authorizes(self):
        resp = self.client.get("/api/tasks", headers={"Authorization": f"Bearer {self.token}"})
        self.assertEqual(resp.status_code, 200)

    def test_query_token_sets_cookie(self):
        resp = self.client.get(f"/?token={self.token}")
        self.assertEqual(resp.status_code, 302)
        # test_client 自动保留 Cookie, 后续请求无需再带令牌
        resp = self.client.get("/api/tasks")
        self.assertEqual(resp.status_code, 200)

    def test_cross_site_write_blocked(self):
        """CSRF 防线: 携带跨站 Fetch Metadata 的写请求即使持令牌也被拒。"""
        resp = self.client.post(
            "/api/copy/validate",
            json={"platform": "douyin", "title": "x"},
            headers={"X-MPAU-Token": self.token, "Sec-Fetch-Site": "cross-site"},
        )
        self.assertEqual(resp.status_code, 403)

    def test_same_origin_write_allowed(self):
        resp = self.client.post(
            "/api/copy/validate",
            json={"platform": "douyin", "title": "x"},
            headers={"X-MPAU-Token": self.token, "Sec-Fetch-Site": "same-origin"},
        )
        self.assertEqual(resp.status_code, 200)


class QrcodeWhitelistTests(unittest.TestCase):
    """/qrcodes/<name> 只允许登录二维码 PNG, 不得借此下载 cookies/ 下的会话文件。"""

    def setUp(self):
        self.client = webapp.app.test_client()
        self.auth = {"X-MPAU-Token": webapp.web_token()}
        self.tmp = Path(tempfile.mkdtemp(prefix="mpau-cookies-"))
        (self.tmp / "douyin_s1_login_qrcode_20260820_101010.png").write_bytes(b"png")
        (self.tmp / "douyin_s1.json").write_text("{}", encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_qrcode_png_served(self):
        with mock.patch.object(webapp, "COOKIES_DIR", self.tmp):
            resp = self.client.get("/qrcodes/douyin_s1_login_qrcode_20260820_101010.png", headers=self.auth)
        self.assertEqual(resp.status_code, 200)

    def test_cookie_json_blocked(self):
        with mock.patch.object(webapp, "COOKIES_DIR", self.tmp):
            resp = self.client.get("/qrcodes/douyin_s1.json", headers=self.auth)
        self.assertEqual(resp.status_code, 404)

    def test_traversal_blocked(self):
        with mock.patch.object(webapp, "COOKIES_DIR", self.tmp):
            resp = self.client.get("/qrcodes/..%2F..%2Fdata%2Fconfig.json", headers=self.auth)
        self.assertEqual(resp.status_code, 404)


class BatchReportValidationTests(unittest.TestCase):
    def setUp(self):
        self.client = webapp.app.test_client()
        self.auth = {"X-MPAU-Token": webapp.web_token()}

    def test_report_rejects_traversal_batch_id(self):
        resp = self.client.get("/api/batch/report?batch_id=../../evil", headers=self.auth)
        self.assertEqual(resp.status_code, 400)

    def test_report_rejects_odd_chars(self):
        resp = self.client.get("/api/batch/report?batch_id=b..1", headers=self.auth)
        self.assertEqual(resp.status_code, 400)


class SettingsTestSsrfTests(unittest.TestCase):
    """/api/settings/test: 沿用已保存 Key 时不允许调用方改 base_url(防真实 Key 被外带)。"""

    SAVED = {
        "llm": {"base_url": "https://api.deepseek.com/v1", "model": "deepseek-chat", "api_key": "sk-real"},
        "scheduler": {},
    }

    def setUp(self):
        self.client = webapp.app.test_client()
        self.auth = {"X-MPAU-Token": webapp.web_token()}

    def _post(self, llm):
        captured = {}

        def fake_call(messages, cfg, temperature=None):
            captured.update(cfg)
            return "正常"

        with mock.patch.object(webapp, "load_config", return_value=self.SAVED), \
             mock.patch("pipeline.copy_engine._call_llm", side_effect=fake_call):
            resp = self.client.post("/api/settings/test", json={"llm": llm}, headers=self.auth)
        return resp, captured

    def test_masked_key_cannot_change_base_url(self):
        resp, captured = self._post({"api_key": "sk-****", "base_url": "http://evil.example.com"})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.get_json()["ok"])
        self.assertEqual(captured.get("base_url"), "https://api.deepseek.com/v1")
        self.assertEqual(captured.get("api_key"), "sk-real")

    def test_empty_key_cannot_change_base_url(self):
        _, captured = self._post({"api_key": "", "base_url": "http://evil.example.com"})
        self.assertEqual(captured.get("base_url"), "https://api.deepseek.com/v1")
        self.assertEqual(captured.get("api_key"), "sk-real")

    def test_new_key_may_change_base_url(self):
        resp, captured = self._post({"api_key": "sk-new", "base_url": "http://192.168.1.9:11434/v1"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(captured.get("base_url"), "http://192.168.1.9:11434/v1")
        self.assertEqual(captured.get("api_key"), "sk-new")

    def test_non_http_base_url_rejected(self):
        resp, _ = self._post({"api_key": "sk-new", "base_url": "ftp://evil.example.com"})
        self.assertEqual(resp.status_code, 400)


if __name__ == "__main__":
    unittest.main()
