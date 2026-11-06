"""出网路径选择：代理坏了要能自动退回直连

背景（真实踩到过的坑）：
    代理地址配着、端口开着、TCP 也连得上，
    但代理往上游取东西时一直挂着不返回 —— 连接建立了，一个字节也不回。
    而**直连是通的**。

    这时候应用如果死抱代理不放，用户看到的是
    「访问 GitHub 超时（8 秒）：容器到 api.github.com 的链路不通」——
    把矛头指向容器出网，可容器出网好着呢。

这些用例不碰真网络：用本地起一个「假代理」来模拟各种故障形态。
"""
from __future__ import annotations

import asyncio
import socket
import sys
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
# 把 tests 目录自己也加进去：护栏模块 _guard 就住在旁边。
# （unittest discover 会自动加，但单跑 unittest 时不会。）
sys.path.insert(0, str(Path(__file__).resolve().parent))

# 护栏：测试绝不能连到线上库（见 tests/_guard.py 的说明）
import _guard  # noqa: E402

_TMP = _guard.use_temp_db()

from app.services import netroute  # noqa: E402
from app.services.netroute import Route, RouteError  # noqa: E402


class _FakeServer(threading.Thread):
    """本地假服务器，模拟各种代理/服务端行为

    行为由 mode 决定：
      - "ok"      ：正常回应
      - "hang"    ：接受连接后一直不回应（这就是那个「假活」的代理）
      - "refuse"  ：立刻断开
    """

    def __init__(self, mode: str = "ok"):
        super().__init__(daemon=True)
        self.mode = mode
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(8)
        self.port = self.sock.getsockname()[1]
        self._stop = threading.Event()

    def run(self):
        while not self._stop.is_set():
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            if self.mode == "hang":
                # 接受连接但永不回应 —— 这正是最阴的那种坏法
                threading.Thread(target=self._hang, args=(conn,), daemon=True).start()
                continue
            if self.mode == "refuse":
                try:
                    conn.close()
                except OSError:
                    pass
                continue
            try:
                conn.recv(65536)
                conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\n{}")
            except OSError:
                pass
            finally:
                try:
                    conn.close()
                except OSError:
                    pass

    def _hang(self, conn):
        self._stop.wait(30)
        try:
            conn.close()
        except OSError:
            pass

    def stop(self):
        self._stop.set()
        try:
            self.sock.close()
        except OSError:
            pass

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"


class TestRouteFallback(unittest.TestCase):
    """路由选择的核心行为"""

    def test_no_proxy_goes_direct(self):
        srv = _FakeServer("ok")
        srv.start()
        try:
            route = asyncio.run(netroute.resolve_route(
                "", timeout=5.0, probe_url=srv.url))
            self.assertTrue(route.direct_ok)
            self.assertFalse(route.use_proxy)
            self.assertFalse(route.bypassed)
        finally:
            srv.stop()

    def test_working_proxy_is_used(self):
        srv = _FakeServer("ok")
        srv.start()
        try:
            route = asyncio.run(netroute.resolve_route(
                srv.url, timeout=5.0, probe_url=srv.url))
            self.assertTrue(route.proxy_ok)
            self.assertTrue(route.use_proxy)
            self.assertFalse(route.bypassed)
        finally:
            srv.stop()

    def test_dead_proxy_falls_back_to_direct(self):
        """核心用例：代理假活、直连能通 → 必须自动走直连，不能报失败"""
        dead = _FakeServer("hang")
        good = _FakeServer("ok")
        dead.start()
        good.start()
        try:
            route = asyncio.run(netroute.resolve_route(
                dead.url, timeout=1.5, probe_url=good.url))
            self.assertFalse(route.proxy_ok)
            self.assertTrue(route.direct_ok)
            self.assertTrue(route.bypassed)
            self.assertFalse(route.use_proxy)
            # 必须明确说出来，不能装作一切正常
            self.assertIn("直连", route.describe())
        finally:
            dead.stop()
            good.stop()

    def test_both_dead_raises_route_error(self):
        dead = _FakeServer("hang")
        dead.start()
        try:
            with self.assertRaises(RouteError) as ctx:
                asyncio.run(netroute.fetch(
                    dead.url, proxy=dead.url, timeout=1.5))
            self.assertFalse(ctx.exception.route.proxy_ok)
            self.assertFalse(ctx.exception.route.direct_ok)
        finally:
            dead.stop()

    def test_route_error_is_httpx_error(self):
        """继承 httpx.HTTPError：上层原有的 except 链不能漏网"""
        self.assertTrue(issubclass(RouteError, Exception))
        import httpx
        self.assertTrue(issubclass(RouteError, httpx.HTTPError))

    def test_probe_reports_both_paths(self):
        dead = _FakeServer("hang")
        good = _FakeServer("ok")
        dead.start()
        good.start()
        try:
            out = asyncio.run(netroute.probe_paths(
                dead.url, timeout=1.5, probe_url=good.url))
            self.assertFalse(out["proxy_ok"])
            self.assertTrue(out["direct_ok"])
            self.assertTrue(out["bypassed"])
            # 耗时也要报出来 —— 用户要靠它判断是「慢」还是「死」
            self.assertGreater(out["proxy_ms"], 0)
            self.assertGreater(out["direct_ms"], 0)
            self.assertIn("直连", out["note"])
        finally:
            dead.stop()
            good.stop()

    def test_probe_without_proxy(self):
        good = _FakeServer("ok")
        good.start()
        try:
            out = asyncio.run(netroute.probe_paths(
                "", timeout=5.0, probe_url=good.url))
            self.assertFalse(out["proxy_configured"])
            self.assertTrue(out["direct_ok"])
            self.assertFalse(out["bypassed"])
        finally:
            good.stop()


class TestRouteDescribe(unittest.TestCase):
    """说给人听的文案"""

    def test_describe_variants(self):
        self.assertEqual(Route().describe(), "直连")
        self.assertEqual(
            Route(proxy="http://x", proxy_ok=True).describe(), "经由代理")
        self.assertIn("直连", Route(proxy="http://x", bypassed=True).describe())
        self.assertIn("都不通",
                      Route(proxy="http://x").describe())


if __name__ == "__main__":
    unittest.main()
