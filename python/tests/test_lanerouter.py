import asyncio
import hashlib
import hmac
import json
import logging
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import lanerouter
from lanerouter import LaneRouter, LaneRouterError, RedLightError, classify, road_of, verify_signature


class FakeApi:
    def __init__(self, light="green", condition="clear"):
        self.light = light
        self.condition = condition
        self.calls = []

    def __call__(self, method, url, headers, body, timeout):
        self.calls.append({"method": method, "url": url, "headers": headers, "body": json.loads(body) if body else None})
        if "/api/v1/check" in url:
            return 200, json.dumps({"condition": self.condition, "light": self.light, "advice": "Use the official API.", "detours": []}).encode()
        if url.endswith("/api/v1/reports"):
            return 202, b'{"accepted": 1}'
        if url.endswith("/api/v1/watches") and method == "POST":
            if not json.loads(body)["url"].startswith("https://"):
                return 422, b'{"error": "url must use https."}'
            return 201, b'{"id": 7, "secret": "whsec_x"}'
        if url.endswith("/api/v1/watches"):
            return 200, b'{"watches": [{"id": 7}]}'
        return 404, b"{}"

    def reports(self):
        out = []
        for c in self.calls:
            if c["url"].endswith("/api/v1/reports"):
                out.extend(c["body"]["reports"])
        return out


class Site(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/blocked"):
            body = b"<html><title>Just a moment...</title></html>"
            self.send_response(403)
            self.send_header("content-type", "text/html")
        else:
            body = b"ok"
            self.send_response(200)
            self.send_header("content-type", "text/plain")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


class Basics(unittest.TestCase):
    def test_road_of_keeps_one_meaningful_segment(self):
        self.assertEqual(road_of("api.github.com/repos/acme/app/pulls")["name"], "api.github.com/repos")
        self.assertEqual(road_of("https://www.delta.com/booking/ABC123XYZ456789?x=1")["name"], "delta.com/booking")
        self.assertEqual(road_of("openrouter.ai/api/v1/models")["name"], "openrouter.ai/api/v1/models")
        self.assertEqual(road_of("https://shop.example.com/9f8e7d6c5b4a3210/orders")["name"], "shop.example.com")
        self.assertIsNone(road_of("http://192.168.1.4/admin"))
        self.assertIsNone(road_of("http://localhost:3000/x"))
        self.assertIsNone(road_of("ftp://files.example.com"))

    def test_classify(self):
        self.assertEqual(classify(200, 10), "clear")
        self.assertEqual(classify(200, 9000), "slow")
        self.assertEqual(classify(429), "rate_limited")
        self.assertEqual(classify(403), "wall")
        self.assertEqual(classify(200, 0, "<title>Just a moment...</title>"), "wall")
        self.assertEqual(classify(502), "broken")
        self.assertEqual(classify(404), "changed")

    def test_verify_signature(self):
        secret, body = "whsec_test", '{"light":"red"}'
        t = int(time.time())
        sig = hmac.new(secret.encode(), f"{t}.{body}".encode(), hashlib.sha256).hexdigest()
        header = f"t={t},v1={sig}"
        self.assertTrue(verify_signature(body, header, secret))
        self.assertTrue(verify_signature(body.encode(), header, secret))
        self.assertFalse(verify_signature(body + " ", header, secret))
        self.assertFalse(verify_signature(body, header, "whsec_other"))
        self.assertFalse(verify_signature(body, header, secret, now=t + 600))
        self.assertFalse(verify_signature(body, None, secret))


class Client(unittest.TestCase):
    def test_reports_are_batched_deduplicated_and_never_leave_ids(self):
        api = FakeApi()
        lanes = LaneRouter(key="lr_test", transport=api, flush_interval=60)
        self.assertTrue(lanes.report("https://shop.example/orders/9f8e7d6c5b4a3210?token=abc", "wall", http_status=403))
        self.assertFalse(lanes.report("https://shop.example/orders/123", "wall"))
        self.assertTrue(lanes.report("https://shop.example/orders/123", "clear"))
        lanes.flush()
        sent = api.reports()
        self.assertEqual([r["target"] for r in sent], ["shop.example/orders", "shop.example/orders"])
        self.assertNotIn("9f8e", json.dumps(sent))
        self.assertNotIn("token", json.dumps(sent))
        self.assertEqual(sent[0]["framework"], "lanerouter-py")
        self.assertEqual(api.calls[-1]["headers"]["authorization"], "Bearer lr_test")

    def test_no_key_means_no_reports_and_endpoint_is_skipped(self):
        api = FakeApi()
        self.assertFalse(LaneRouter(key=None, transport=api).report("shop.example", "clear"))
        lanes = LaneRouter(key="lr_test", transport=api)
        self.assertFalse(lanes.report("https://lanerouter.com/api/v1/check", "clear"))
        with self.assertRaises(ValueError):
            lanes.report("shop.example", "exploded")

    def test_checks_are_cached_and_block_mode_raises_on_red(self):
        api = FakeApi(light="red", condition="wall")
        lanes = LaneRouter(key="lr_test", transport=api, check="block")
        lanes.check("shop.example/checkout")
        lanes.check("shop.example/checkout")
        self.assertEqual(len([c for c in api.calls if "/check" in c["url"]]), 1)
        with self.assertRaises(RedLightError) as ctx:
            lanes.before("https://shop.example/checkout", "POST")
        self.assertEqual(ctx.exception.condition, "wall")

    def test_warn_mode_logs_once_and_on_condition_wins(self):
        api = FakeApi(light="amber", condition="slow")
        lanes = LaneRouter(key="lr_test", transport=api)
        with self.assertLogs("lanerouter", level=logging.WARNING) as logs:
            lanes.before("https://slow.example/search")
            lanes.before("https://slow.example/search")
        self.assertEqual(len(logs.records), 1)
        seen = []
        LaneRouter(key="lr_test", transport=api, on_condition=seen.append).before("https://slow.example/search")
        self.assertEqual(seen[0]["road"], "slow.example/search")

    def test_lanerouter_failures_never_reach_the_caller(self):
        def broken(*args):
            raise OSError("network down")
        lanes = LaneRouter(key="lr_test", transport=broken, check="block")
        self.assertIsNone(lanes.before("https://shop.example/checkout"))
        lanes.report("shop.example", "clear")
        lanes.flush()

    def test_watch_helpers(self):
        api = FakeApi()
        lanes = LaneRouter(key="lr_test", transport=api)
        self.assertEqual(lanes.watch("shop.example/checkout", "https://hooks.example.com/x")["secret"], "whsec_x")
        self.assertEqual(lanes.watches(), [{"id": 7}])
        with self.assertRaises(LaneRouterError) as ctx:
            lanes.watch("shop.example/checkout", "http://hooks.example.com/x")
        self.assertEqual(ctx.exception.status, 422)
        with self.assertRaises(LaneRouterError):
            LaneRouter(key=None, transport=api).watches()


class Patching(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Site)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def lanes(self, api):
        lanes = LaneRouter(key="lr_test", transport=api, flush_interval=60)
        lanes._skip = lambda road: False
        lanerouter_road = lanerouter.road_of
        lanerouter.road_of = lambda target: lanerouter_road(str(target).replace("127.0.0.1", "site.example"))
        self.addCleanup(setattr, lanerouter, "road_of", lanerouter_road)
        return lanes

    def test_requests_is_checked_and_reported(self):
        try:
            import requests
        except ImportError:
            self.skipTest("requests not installed")
        api = FakeApi()
        lanes = self.lanes(api)
        lanes.install()
        try:
            self.assertEqual(requests.get(self.base + "/blocked").status_code, 403)
            requests.get(self.base + "/fine")
        finally:
            lanes.uninstall()
        lanes.flush()
        self.assertEqual([(r["target"], r["outcome"]) for r in api.reports()], [("site.example/blocked", "wall"), ("site.example/fine", "clear")])
        self.assertTrue(any("/check" in c["url"] for c in api.calls))
        requests.get(self.base + "/fine")
        self.assertEqual(len(api.reports()), 2)

    def test_httpx_sync_and_async_are_checked_and_reported(self):
        try:
            import httpx
        except ImportError:
            self.skipTest("httpx not installed")
        api = FakeApi()
        lanes = self.lanes(api)
        lanes.install()
        try:
            with httpx.Client() as client:
                client.get(self.base + "/blocked")

            async def run():
                async with httpx.AsyncClient() as client:
                    await client.get(self.base + "/fine")

            asyncio.run(run())
        finally:
            lanes.uninstall()
        lanes.flush()
        self.assertEqual([(r["target"], r["outcome"]) for r in api.reports()], [("site.example/blocked", "wall"), ("site.example/fine", "clear")])


if __name__ == "__main__":
    unittest.main()
