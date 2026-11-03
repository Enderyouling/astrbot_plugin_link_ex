"""Host API stubs exercise actual plugin methods without an AstrBot deployment."""

import asyncio
import importlib.util
import io
from pathlib import Path
import sys
import time
import types
import unittest
from unittest.mock import AsyncMock, patch

from tests._stub import install

install()
import astrbot.api
import httpx
import fetchers
import render
import wordfilter


def load_plugin():
    root = Path(__file__).resolve().parents[1]
    package = types.ModuleType("ex_runtime_test")
    package.__path__ = [str(root)]
    sys.modules[package.__name__] = package
    for name, module in (
        ("fetchers", fetchers),
        ("render", render),
        ("wordfilter", wordfilter),
    ):
        sys.modules[package.__name__ + "." + name] = module
    star = types.ModuleType("astrbot.api.star")
    star.Context = star.Star = star.StarTools = object
    event = types.ModuleType("astrbot.api.event")
    event.AstrMessageEvent = event.MessageChain = object
    decorator = lambda *a, **k: lambda fn: fn
    event.filter = types.SimpleNamespace(
        command=decorator,
        event_message_type=decorator,
        on_decorating_result=decorator,
        permission_type=decorator,
        EventMessageType=types.SimpleNamespace(ALL=1),
        PermissionType=types.SimpleNamespace(ADMIN=1),
    )
    components = types.ModuleType("astrbot.api.message_components")
    components.Json = type("Json", (), {})
    spec = importlib.util.spec_from_file_location(
        package.__name__ + ".main", root / "main.py"
    )
    module = importlib.util.module_from_spec(spec)
    with (
        patch.dict(
            sys.modules,
            {
                star.__name__: star,
                event.__name__: event,
                components.__name__: components,
            },
        ),
        patch.object(astrbot.api, "AstrBotConfig", dict, create=True),
    ):
        spec.loader.exec_module(module)
    return module


plugin = load_plugin()


class RuntimeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.p = plugin.LinkPreviewPlugin.__new__(plugin.LinkPreviewPlugin)
        self.p.config = {"max_concurrent_previews": 1}
        self.p._active_jobs = 0
        self.p._x_replies = {}

    async def test_admission_rejects_excess_and_recovers_after_cancellation(self):
        entered = asyncio.Event()

        async def job():
            async with self.p._preview_slot():
                entered.set()
                await asyncio.Event().wait()

        task = asyncio.create_task(job())
        await entered.wait()
        with self.assertRaises(RuntimeError):
            async with self.p._preview_slot():
                self.fail("admitted excess task")
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        self.assertEqual(self.p._active_jobs, 0)
        async with self.p._preview_slot():
            self.assertEqual(self.p._active_jobs, 1)

    async def test_x_timeout_cancels_work(self):
        cancelled = asyncio.Event()

        async def fetch(*a, **k):
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        with (
            patch.object(
                self.p,
                "_x_service",
                return_value=("http://configured-service", "token"),
            ),
            patch.object(fetchers, "fetch_x_replies", new=fetch),
        ):
            self.assertEqual(
                await self.p._x_replies_for("https://x.com/a/status/123", 3, 0.02), []
            )
        self.assertTrue(cancelled.is_set())

    async def test_render_preparation_does_not_block_event_loop(self):
        ticks = 0

        def prepare(*a):
            time.sleep(0.05)
            return {"font_css": "font"}

        async def tick():
            nonlocal ticks
            for _ in range(10):
                await asyncio.sleep(0.003)
                ticks += 1

        async def render_image(*a, **k):
            self.assertGreater(ticks, 0, "font preparation blocked other tasks")
            return "image"

        with (
            patch.object(render, "card_data", side_effect=prepare),
            patch.object(self.p, "_t2i", new=render_image),
        ):
            await asyncio.gather(self.p._render_html(None, {}, None), tick())
            self.assertEqual(ticks, 10)

    def test_translation_is_filtered(self):
        self.p.filter = wordfilter.WordFilter(None, ["blockedtoken"])
        self.p.restricted = wordfilter.WordFilter(None, ["restrictedtoken"])
        for text, error in (
            ("blockedtoken", plugin.Blocked),
            ("restrictedtoken", plugin.RestrictedBlocked),
        ):
            with self.assertRaises(error):
                self.p._filter_card({"title": "clean", "translation": text})

    def test_manual_command_cannot_bypass_domain_blocklist(self):
        self.p.config["web_blocklist"] = ["example.com"]
        event = types.SimpleNamespace(
            message_str="/预览 https://sub.example.com/a", get_messages=lambda: []
        )
        self.assertEqual(self.p._links_from_command(event), [])

    async def test_remembered_links_cannot_bypass_domain_blocklist(self):
        self.p.config["web_blocklist"] = ["example.com"]
        for method in (self.p._make_card_image, self.p._render_article):
            with self.assertRaises(fetchers.FetchError):
                await method("web", "https://sub.example.com/a")

    async def test_new_platforms_use_public_metadata_and_reject_foreign_redirect(self):
        for platform, host in (
            ("kuaishou", "v.kuaishou.com"),
            ("ixigua", "www.ixigua.com"),
            ("vqq", "v.qq.com"),
            ("youku", "v.youku.com"),
            ("iqiyi", "www.iqiyi.com"),
        ):
            url = f"https://{host}/sample"
            self.assertEqual(
                fetchers.find_links(url, {platform: True}), [(platform, url)]
            )
            async with httpx.AsyncClient(
                transport=httpx.MockTransport(
                    lambda r: httpx.Response(
                        200, text='<meta property="og:title" content="Public video">'
                    )
                )
            ) as client:
                self.assertEqual(
                    (await fetchers.fetch(client, platform, url))["title"],
                    "Public video",
                )
            async with httpx.AsyncClient(
                transport=httpx.MockTransport(
                    lambda r: httpx.Response(
                        302, headers={"location": "https://evil.example/"}
                    )
                )
            ) as client:
                with self.assertRaises(fetchers.FetchError):
                    await fetchers.fetch(client, platform, url)

    async def test_oversized_pixel_image_rejected(self):
        from PIL import Image

        buffer = io.BytesIO()
        Image.new("1", (5000, 5000)).save(buffer, "PNG")
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda r: httpx.Response(
                    200,
                    headers={"content-type": "image/png"},
                    content=buffer.getvalue(),
                )
            )
        ) as client:
            self.assertEqual(
                await render._image_info(client, "https://example.com/a.png"),
                (None, 0, 0),
            )

    def test_font_cache_is_bounded_and_hit_is_reused(self):
        render._subset_b64.cache_clear()
        path = render.FONTS[0][0]
        first = render._subset_b64(path, "cache test")
        with patch("fontTools.ttLib.TTFont", side_effect=AssertionError("cache miss")):
            self.assertEqual(render._subset_b64(path, "cache test"), first)
        self.assertEqual(render._subset_b64.cache_info().maxsize, 40)
