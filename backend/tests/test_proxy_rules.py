"""出站代理地址的校验与归一化

要挡住的几类坑：
  · scheme 写错（写成 ftp://、或干脆没写协议）
  · 端口不合法
  · 带路径
  · **填了 127.0.0.1** —— 容器里它指向容器自己，不是宿主机
  · 代理认证的用户名口令被改写弄丢
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import _guard  # noqa: E402,F401

from app.services.settings_store import normalize_proxy  # noqa: E402


class TestNormalizeProxy(unittest.TestCase):

    def test_empty_is_valid(self):
        # 空 = 不配代理 = 直连，是合法状态，不是错误
        self.assertEqual(normalize_proxy(""), ("", "", ""))
        self.assertEqual(normalize_proxy(None), ("", "", ""))

    def test_plain_http(self):
        value, err, warn = normalize_proxy("http://10.10.10.252:1086")
        self.assertEqual(value, "http://10.10.10.252:1086")
        self.assertEqual(err, "")
        self.assertEqual(warn, "")

    def test_trailing_slash_removed(self):
        # 同一台代理写成两种样子不该被当成两个配置
        value, _, _ = normalize_proxy("http://proxy.local:3128/")
        self.assertEqual(value, "http://proxy.local:3128")

    def test_bad_scheme_rejected(self):
        _, err, _ = normalize_proxy("ftp://proxy.local:3128")
        self.assertTrue(err)
        _, err, _ = normalize_proxy("proxy.local:3128")
        self.assertTrue(err)

    def test_missing_host_rejected(self):
        _, err, _ = normalize_proxy("http://:3128")
        self.assertTrue(err)

    def test_bad_port_rejected(self):
        _, err, _ = normalize_proxy("http://proxy.local:99999")
        self.assertTrue(err)

    def test_path_rejected(self):
        _, err, _ = normalize_proxy("http://proxy.local:3128/path")
        self.assertTrue(err)

    def test_https_accepted(self):
        value, err, _ = normalize_proxy("https://proxy.local:3128")
        self.assertEqual(value, "https://proxy.local:3128")
        self.assertEqual(err, "")

    def test_socks5_accepted_when_component_present(self):
        """socks5 要看镜像里有没有 socksio 组件

        没有组件时**必须给一句人话**，而不是让 httpx 在运行时抛一个
        「SOCKS proxy requires the socksio package」这种天书。
        """
        try:
            import socksio  # noqa: F401
            have = True
        except ImportError:
            have = False
        value, err, _ = normalize_proxy("socks5://10.10.10.252:1080")
        if have:
            self.assertEqual(err, "")
            self.assertEqual(value, "socks5://10.10.10.252:1080")
        else:
            # 没有组件：拒绝，并且说清楚为什么、怎么办
            self.assertTrue(err)
            self.assertIn("socksio", err)
            self.assertIn("http", err)

    # ---- 回环地址改写：容器里最经典的坑 ----

    def test_loopback_rewritten_to_gateway(self):
        value, err, warn = normalize_proxy("http://127.0.0.1:7890")
        self.assertEqual(err, "")
        self.assertEqual(value, "http://host.docker.internal:7890")
        # 必须明确说出来 —— 静默改写只会让人更困惑
        self.assertIn("host.docker.internal", warn)
        self.assertIn("127.0.0.1", warn)

    def test_localhost_rewritten(self):
        value, err, warn = normalize_proxy("http://localhost:7890")
        self.assertEqual(err, "")
        self.assertEqual(value, "http://host.docker.internal:7890")
        self.assertTrue(warn)

    def test_loopback_with_credentials_keeps_auth(self):
        # 代理认证很常见，改写时把 user:pass@ 弄丢就等于把代理配坏了
        value, err, _ = normalize_proxy("http://user:pa%3Ass@127.0.0.1:7890")
        self.assertEqual(err, "")
        self.assertIn("user:pa%3Ass@", value)
        self.assertIn("host.docker.internal:7890", value)

    def test_non_loopback_untouched(self):
        value, _, warn = normalize_proxy("http://10.10.10.252:1086")
        self.assertEqual(value, "http://10.10.10.252:1086")
        self.assertEqual(warn, "")


if __name__ == "__main__":
    unittest.main()
