"""Offline regression checks for public previews and domestic share links."""

import socket
import unittest
from unittest.mock import patch, AsyncMock

from tests._stub import install

install()
import httpx
import fetchers
import render
from safe_http import PublicTransport, PreviewClient, LimitedStream


class DomesticTests(unittest.IsolatedAsyncioTestCase):
    async def test_x_fallback_does_not_use_authenticated_post(self):
        with (
            patch.object(
                fetchers, "_x_card", new=AsyncMock(side_effect=fetchers.FetchError())
            ),
            patch.object(
                fetchers, "fetch_og", new=AsyncMock(return_value={"text": "public"})
            ) as og,
        ):
            result = await fetchers.fetch_x(
                None, "https://x.com/a/status/1", ("http://internal", "token")
            )
            self.assertEqual(result["text"], "public")
            og.assert_awaited_once()

    async def test_authenticated_x_reply_text_not_published(self):
        service = httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda r: httpx.Response(
                    200, json={"items": [{"id": "2", "text": "private"}]}
                )
            )
        )
        with (
            patch.object(fetchers.httpx, "AsyncClient", return_value=service),
            patch.object(
                fetchers, "_x_card", new=AsyncMock(side_effect=fetchers.FetchError())
            ),
        ):
            self.assertEqual(
                await fetchers.fetch_x_replies("http://internal", "test", "1"), []
            )

    def test_recognition_and_host_boundaries(self):
        examples = {
            "bilibili": "https://www.bilibili.com/video/BV1xx411c7mD/",
            "douyin": "https://v.douyin.com/AbCd/",
            "xiaohongshu": "https://xhslink.com/a/AbCd",
            "weibo": "https://m.weibo.cn/detail/123456",
            "zhihu": "https://www.zhihu.com/question/123/answer/456",
        }
        for platform, url in examples.items():
            self.assertEqual(
                fetchers.find_links(url, {platform: True}), [(platform, url)]
            )
            self.assertEqual(fetchers.find_links(url, {platform: False}), [])
            self.assertEqual(
                fetchers.find_links(
                    url.replace("https://", "https://evil.invalid/"), {platform: True}
                ),
                [],
            )

    async def test_bilibili_short_link_and_api(self):
        def handler(request):
            if request.url.host == "b23.tv":
                return httpx.Response(
                    302,
                    headers={
                        "location": "https://www.bilibili.com/video/BV1xx411c7mD/"
                    },
                )
            self.assertEqual(request.url.host, "api.bilibili.com")
            self.assertEqual(request.url.params["bvid"], "BV1xx411c7mD")
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {
                        "title": "测试",
                        "owner": {"name": "UP"},
                        "duration": 62,
                        "stat": {"view": 12345},
                    },
                },
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            card = await fetchers.fetch(client, "bilibili", "https://b23.tv/test")
        self.assertEqual(card["title"], "测试")
        self.assertEqual(card["duration"], "1:02")

    async def test_share_metadata_for_all_other_platforms(self):
        for platform, host in (
            ("douyin", "www.douyin.com"),
            ("xiaohongshu", "www.xiaohongshu.com"),
            ("weibo", "weibo.com"),
            ("zhihu", "www.zhihu.com"),
        ):
            page = '<meta property="og:title" content="公开内容"><meta name="description" content="说明"><meta property="og:image" content="/cover.jpg">'
            async with httpx.AsyncClient(
                transport=httpx.MockTransport(lambda r: httpx.Response(200, text=page))
            ) as client:
                result = await fetchers.fetch(client, platform, f"https://{host}/item")
                self.assertEqual(result["images"], [f"https://{host}/cover.jpg"])

    async def test_share_redirect_and_login_rejected(self):
        for response in (
            httpx.Response(302, headers={"location": "http://127.0.0.1/"}),
            httpx.Response(200, text="<title>安全验证</title>"),
        ):
            async with httpx.AsyncClient(
                transport=httpx.MockTransport(lambda r: response)
            ) as client:
                with self.assertRaises(fetchers.FetchError):
                    await fetchers.fetch(client, "douyin", "https://v.douyin.com/test/")

    async def test_private_github_issue_never_fetched(self):
        paths = []

        def handler(request):
            paths.append(request.url.path)
            return httpx.Response(200, json={"private": True, "visibility": "private"})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with self.assertRaises(fetchers.FetchError):
                await fetchers.fetch_github(
                    client, "https://github.com/owner/private/issues/1", token="test"
                )
        self.assertEqual(paths, ["/repos/owner/private"])


class NetworkTests(unittest.IsolatedAsyncioTestCase):
    async def test_private_dns_and_redirects_blocked(self):
        for address in (
            "127.0.0.1",
            "10.0.0.1",
            "169.254.169.254",
            "::1",
            "fc00::1",
            "224.0.0.1",
            "ff02::1",
        ):
            transport = PublicTransport()
            with patch(
                "safe_http.socket.getaddrinfo",
                return_value=[
                    (socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 80))
                ],
            ):
                async with httpx.AsyncClient(transport=transport) as client:
                    with self.assertRaises(httpx.RequestError):
                        await client.get("https://example.com/")

    async def test_dns_pinned_and_redirect_revalidated(self):
        calls = []

        def handler(request):
            calls.append(request)
            self.assertEqual(request.url.host, "8.8.8.8")
            self.assertEqual(request.headers["host"], "example.com")
            self.assertEqual(request.extensions["sni_hostname"], "example.com")
            return httpx.Response(302, headers={"location": "http://localhost/"})

        transport = PublicTransport()
        await transport.inner.aclose()
        transport.inner = httpx.MockTransport(handler)

        def resolve(host, *args, **kw):
            return [
                (
                    socket.AF_INET,
                    socket.SOCK_STREAM,
                    6,
                    "",
                    ("8.8.8.8" if host == "example.com" else "127.0.0.1", 443),
                )
            ]

        with patch("safe_http.socket.getaddrinfo", side_effect=resolve):
            async with httpx.AsyncClient(
                transport=transport, follow_redirects=True
            ) as client:
                with self.assertRaises(httpx.RequestError):
                    await client.get("https://example.com/")
        self.assertEqual(len(calls), 1)

    async def test_body_and_image_limits(self):
        class Chunks(httpx.AsyncByteStream):
            async def __aiter__(self):
                for _ in range(10):
                    yield b"x" * (1024 * 1024)

        async with PreviewClient(
            transport=httpx.MockTransport(
                lambda r: httpx.Response(200, stream=Chunks())
            )
        ) as client:
            with self.assertRaises(httpx.RequestError):
                await client.get("https://example.com/")
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda r: httpx.Response(
                    200, headers={"content-type": "image/png"}, stream=Chunks()
                )
            )
        ) as client:
            self.assertIsNone(
                await render._data_uri(
                    client, "https://example.com/image", max_bytes=1024
                )
            )
        with self.assertRaises(httpx.RequestError):
            async for _ in LimitedStream(Chunks()):
                pass

    async def test_svg_rejected(self):
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda r: httpx.Response(
                    200, headers={"content-type": "image/svg+xml"}, text="<svg/>"
                )
            )
        ) as client:
            self.assertIsNone(
                await render._data_uri(client, "https://example.com/image")
            )
