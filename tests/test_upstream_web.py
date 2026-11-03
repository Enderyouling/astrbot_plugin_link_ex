import asyncio
import unittest
from tests.test_fetchers import ALL_ON
import fetchers


class TestWebFallback(unittest.TestCase):
    """没被任何平台匹配到的链接按通用网页预览，但要挡掉内网和直链文件。"""

    def test_unknown_site_falls_back_to_web(self):
        got = fetchers.find_links("https://example.com/post/1", ALL_ON)
        self.assertEqual(got, [("web", "https://example.com/post/1")])

    def test_known_platform_still_wins(self):
        self.assertEqual(
            fetchers.find_links("https://github.com/o/r", ALL_ON)[0][0], "github"
        )

    def test_private_hosts_skipped(self):
        for url in (
            "http://localhost:8080/x",
            "http://192.168.1.1/admin",
            "http://10.0.0.5/",
            "http://172.16.3.4/",
            "http://127.0.0.1:6199/",
            "http://nas.local/",
            "http://intranet/",
        ):
            self.assertEqual(fetchers.find_links(url, ALL_ON), [], url)

    def test_direct_files_skipped(self):
        for url in (
            "https://example.com/a.jpg",
            "https://example.com/doc.pdf",
            "https://example.com/pack.zip",
            "https://example.com/app.apk",
        ):
            self.assertEqual(fetchers.find_links(url, ALL_ON), [], url)

    def test_blocklist_covers_subdomains(self):
        blocked = ["bilibili.com"]
        for url in (
            "https://www.bilibili.com/video/BV1xx",
            "https://live.bilibili.com/123",
        ):
            self.assertEqual(fetchers.find_links(url, ALL_ON, 3, blocked), [], url)
        self.assertTrue(
            fetchers.find_links("https://example.com/x", ALL_ON, 3, blocked)
        )

    def test_blocked_link_does_not_use_up_limit(self):
        text = "http://192.168.1.1/ https://example.com/x"
        self.assertEqual(
            fetchers.find_links(text, ALL_ON, 1), [("web", "https://example.com/x")]
        )

    def test_web_can_be_disabled(self):
        off = dict(ALL_ON, web=False)
        self.assertEqual(fetchers.find_links("https://example.com/x", off), [])

    def test_is_previewable_web(self):
        self.assertTrue(fetchers.is_previewable_web("https://example.com/a/b"))
        self.assertFalse(fetchers.is_previewable_web("ftp://example.com/a"))
        self.assertFalse(fetchers.is_previewable_web("https://example/a"))
        self.assertFalse(fetchers.is_previewable_web(""))


class TestBareUrls(unittest.TestCase):
    """群里常直接发 www.bilibili.com 这种没协议的域名。"""

    def test_bare_domain(self):
        self.assertEqual(
            fetchers.find_links("www.bilibili.com", ALL_ON),
            [("web", "https://www.bilibili.com")],
        )

    def test_bare_domain_with_path(self):
        self.assertEqual(
            fetchers.find_links("看www.bilibili.com/video/BV1xx 这个", ALL_ON),
            [("web", "https://www.bilibili.com/video/BV1xx")],
        )

    def test_bare_domain_keeps_platform(self):
        self.assertEqual(fetchers.find_links("github.com/o/r", ALL_ON)[0][0], "github")
        self.assertEqual(fetchers.find_links("x.com/jack/status/20", ALL_ON)[0][0], "x")

    def test_no_false_positive(self):
        for text in (
            "版本 1.2.3 发布了",
            "文件 file.txt",
            "a@b.com",
            "e.g. this",
            "随便聊聊",
        ):
            self.assertEqual(fetchers.find_links(text, ALL_ON), [], text)

    def test_scheme_url_not_counted_twice(self):
        self.assertEqual(
            fetchers.find_links("https://example.com/x", ALL_ON),
            [("web", "https://example.com/x")],
        )

    def test_chinese_domain(self):
        for text, want in (
            ("中文.中国", "https://中文.中国"),
            ("中国政府.政务", "https://中国政府.政务"),
            ("中文域名.cn", "https://中文域名.cn"),
            ("百度.中国/搜索", "https://百度.中国/搜索"),
        ):
            self.assertEqual(fetchers.find_links(text, ALL_ON), [("web", want)], text)

    def test_chinese_domain_needs_boundary(self):
        """中文域名夹在中文句子里没法分词，宁可不认。"""
        for text in ("看中文.中国这个", "我买了个中文.中国域名"):
            self.assertEqual(fetchers.find_links(text, ALL_ON), [], text)
        # 有分隔就认
        self.assertEqual(
            fetchers.find_links("推荐 中文.中国", ALL_ON),
            [("web", "https://中文.中国")],
        )
        self.assertEqual(
            fetchers.find_links("中文.中国，很好用", ALL_ON),
            [("web", "https://中文.中国")],
        )

    def test_chinese_text_does_not_break_ascii_domain(self):
        self.assertEqual(
            fetchers.find_links("看www.bilibili.com这个", ALL_ON),
            [("web", "https://www.bilibili.com")],
        )

    def test_punycode_domain(self):
        self.assertEqual(
            fetchers.find_links("xn--fiq228c.xn--fiqs8s", ALL_ON),
            [("web", "https://xn--fiq228c.xn--fiqs8s")],
        )

    def test_extra_tlds(self):
        """内置列表之外的顶级域，可以在配置里补充。"""
        self.assertEqual(fetchers.find_links("example.zip", ALL_ON), [])
        self.assertEqual(
            fetchers.find_links("example.zip", ALL_ON, 3, None, ["zip"]),
            [("web", "https://example.zip")],
        )
        self.assertEqual(
            fetchers.find_links("测试.测试域", ALL_ON, 3, None, ["测试域"]),
            [("web", "https://测试.测试域")],
        )

    def test_extra_tlds_normalized(self):
        self.assertEqual(
            fetchers.normalize_tlds([".ZIP", "zip", " 中国 ", "", None]),
            ("zip", "中国"),
        )

    def test_extra_tlds_do_not_leak(self):
        """正则按额外顶级域缓存，两套配置不能互相污染。"""
        self.assertTrue(fetchers.find_links("example.zip", ALL_ON, 3, None, ["zip"]))
        self.assertEqual(fetchers.find_links("example.zip", ALL_ON), [])
        self.assertEqual(fetchers.find_links("example.mov", ALL_ON), [])

    def test_candidate_order(self):
        self.assertEqual(
            fetchers.candidate_urls("先 https://a.com/1 再 b.com/2"),
            ["https://a.com/1", "https://b.com/2"],
        )


class TestCleanSite(unittest.TestCase):
    """og:site_name 常带整句标题，要压成短站名。"""

    def test_takes_head_segment(self):
        self.assertEqual(fetchers.clean_site("少数派 - 高品质数字消费指南"), "少数派")
        self.assertEqual(fetchers.clean_site("BBC News | Breaking news"), "BBC News")
        self.assertEqual(fetchers.clean_site("知乎 · 有问题就会有答案"), "知乎")

    def test_keeps_plain_names(self):
        self.assertEqual(fetchers.clean_site("The GitHub Blog"), "The GitHub Blog")
        self.assertEqual(fetchers.clean_site(""), "")

    def test_punycode_to_chinese(self):
        self.assertEqual(fetchers.pretty_host("xn--fiqs8s"), "中国")
        self.assertEqual(
            fetchers.pretty_host("xn--gmq282eogn.xn--fiqs8s"), "人民网.中国"
        )
        self.assertEqual(fetchers.pretty_host("www.example.com"), "www.example.com")
        self.assertEqual(fetchers.pretty_host("xn--bad-"), "xn--bad-")  # 转不了原样返回

    def test_placeholder_description_dropped(self):
        self.assertIsNone(fetchers.clean_desc("视频播放量 {$0}、弹幕量 {$1}"))
        self.assertEqual(fetchers.clean_desc("正常描述"), "正常描述")
        self.assertIsNone(fetchers.clean_desc(""))


class _FakeResp:
    def __init__(self, text, url, ctype="text/html; charset=utf-8"):
        self.status_code = 200
        self.text = text
        self.content = text.encode()
        self.url = url
        self.headers = {"content-type": ctype}


class _FakeClient:
    def __init__(self, resp):
        self.resp = resp

    async def get(self, url, **kw):
        return self.resp


class TestFetchOgWeb(unittest.TestCase):
    HTML = """<html><head>
      <meta property="og:title" content="一篇文章">
      <meta property="og:description" content="摘要内容">
      <meta property="og:site_name" content="示例站">
      <meta property="og:image" content="/img/cover.png">
      <meta property="article:published_time" content="2026-10-30T10:00:00Z">
      <link rel="icon" href="/favicon.ico">
    </head><body></body></html>"""

    def test_relative_image_and_favicon_resolved(self):
        client = _FakeClient(_FakeResp(self.HTML, "https://example.com/post/1"))
        c = asyncio.run(fetchers.fetch_og(client, "web", "https://example.com/post/1"))
        self.assertEqual(c["title"], "一篇文章")
        self.assertEqual(c["images"], ["https://example.com/img/cover.png"])
        self.assertEqual(c["author"]["avatar"], "https://example.com/favicon.ico")
        # 徽章显示站名，作者行显示域名，避免同一句话出现两次
        self.assertEqual(c["author"]["name"], "example.com")
        self.assertIsNone(c["author"]["handle"])
        self.assertEqual(c["platform_name"], "示例站")
        self.assertTrue(c["time"].startswith("2026-10-30"))

    def test_non_html_rejected(self):
        client = _FakeClient(
            _FakeResp("xx", "https://example.com/a", ctype="image/png")
        )
        with self.assertRaises(fetchers.FetchError):
            asyncio.run(fetchers.fetch_og(client, "web", "https://example.com/a"))

    def test_cert_error_never_downgrades_to_http(self):
        """证书失败必须失败关闭，不自动降级到明文 HTTP。"""

        class CertFailClient:
            def __init__(self):
                self.urls = []

            async def get(self, url, **kw):
                self.urls.append(url)
                if url.startswith("https://"):
                    import httpx

                    raise httpx.ConnectError(
                        "[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed"
                    )
                return _FakeResp(TestFetchOgWeb.HTML, "http://example.com/post/1")

        client = CertFailClient()
        import httpx

        with self.assertRaises(httpx.ConnectError):
            asyncio.run(fetchers.fetch_og(client, "web", "https://example.com/post/1"))
        self.assertEqual(client.urls, ["https://example.com/post/1"])

    def test_login_wall_rejected(self):
        html = "<html><head><title>Log in</title></head></html>"
        client = _FakeClient(_FakeResp(html, "https://example.com/a"))
        with self.assertRaises(fetchers.FetchError):
            asyncio.run(fetchers.fetch_og(client, "web", "https://example.com/a"))
