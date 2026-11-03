"""render 的版式与裁边测试：不联网、不出图，只验 HTML 与裁切逻辑。"""

import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from tests._stub import install  # noqa: E402

install()

import render  # noqa: E402

CARD = {
    "platform": "x",
    "platform_name": "X",
    "color": "#000000",
    "url": "https://x.com/a/status/1",
    "title": None,
    "text": "hi",
    "author": {"name": "a", "handle": "@a", "avatar": None, "bio": ""},
    "images": [],
    "stats": [["回复", "1"]],
    "tags": [],
    "time": "2026-01-01 00:00",
    "comments": [],
    "quote": None,
    "video": False,
    "duration": None,
    "sensitive": False,
    "note": None,
    "comments_mode": False,
    "blur": False,
    "domain": "x.com",
    "short_url": "x.com/a/status/1",
    "icon": "X",
    "no_comments_reason": None,
}


class TestBuildHtml(unittest.TestCase):
    def test_t2i_class_on_body(self):
        html = render.build_html(CARD, "dark")
        self.assertIn('class="dark t2i"', html)

    def test_t2i_can_be_disabled(self):
        html = render.build_html(CARD, "dark", t2i=False)
        self.assertIn('class="dark"', html)
        self.assertNotIn("t2i", html.split("<body")[1][:80])

    def test_latin_font_comes_before_cjk(self):
        """远端 Chromium 缺 Noto CJK 时会退到全角拉丁的字体，DejaVu/sans-serif 必须排在前面。"""
        html = render.build_html(CARD, "dark")
        # 取 body 那条 font-family（@font-face 里也有一处，要跳过）
        stack = html.split('font-family: "LP Sans"', 1)[1].split(";", 1)[0]
        self.assertLess(stack.index("DejaVu Sans"), stack.index("Noto Sans CJK SC"))
        self.assertLess(stack.index("sans-serif"), stack.index("Noto Sans CJK SC"))

    def test_no_local_font_lookup(self):
        """不要用 local() 取本机字体，远端不一定装了；字体是内嵌的。"""
        html = render.build_html(CARD, "dark")
        self.assertNotIn("local(", html)
        self.assertNotIn("PunctFix", html)

    def test_card_fills_t2i_viewport(self):
        html = render.build_html(CARD, "dark")
        self.assertIn("body.t2i { width: 800px; }", html)


class TestMediaLayout(unittest.TestCase):
    """竖图必须走纵向堆叠，否则 cover 会把上下裁掉。"""

    def test_portrait_needs_stack(self):
        self.assertTrue(render.media_needs_stack([(648, 1280)]))
        self.assertTrue(render.media_needs_stack([(800, 600), (648, 1280)]))

    def test_landscape_and_square_use_grid(self):
        self.assertFalse(render.media_needs_stack([(1280, 720)]))
        self.assertFalse(render.media_needs_stack([(600, 600), (800, 400)]))

    def test_empty_or_unknown_sizes(self):
        self.assertFalse(render.media_needs_stack([]))
        self.assertFalse(render.media_needs_stack([(0, 0)]))

    def test_threshold(self):
        self.assertFalse(render.media_needs_stack([(100, 120)]))  # 1.2 仍算横/方
        self.assertTrue(render.media_needs_stack([(100, 130)]))  # 1.3 算竖图

    def test_template_renders_stack_class(self):
        card = dict(CARD, images=["data:image/jpeg;base64,xx"], media_tall=True)
        html = render.build_html(card, "dark")
        self.assertIn("media n1 stack", html)

    def test_template_without_tall(self):
        card = dict(CARD, images=["data:image/jpeg;base64,xx"], media_tall=False)
        self.assertNotIn(
            " stack", render.build_html(card, "dark").split("<body")[1][:2000]
        )


class TestEmbeddedFont(unittest.TestCase):
    """字体要内嵌，否则不同渲染机出来的粗细、字形都不一样。"""

    def test_font_files_present(self):
        for name in ("NotoSansSC-Regular.woff2", "NotoSansSC-Bold.woff2", "OFL.txt"):
            self.assertTrue((render.FONT_DIR / name).exists(), f"缺少 fonts/{name}")

    def test_css_has_both_weights(self):
        css = render.font_css(CARD)
        self.assertIn("@font-face", css)
        self.assertIn("font-weight:400", css)
        self.assertIn("font-weight:700", css)
        self.assertIn("data:font/woff2;base64,", css)

    def test_subset_is_small(self):
        """按字符裁剪后应该远小于整份字体。"""
        css = render.font_css(CARD)
        full = sum(p.stat().st_size for p, _ in render.FONTS)
        self.assertLess(len(css), full, "子集没有比整份字体小，可能没裁")

    def test_html_embeds_font_and_drops_antialiased(self):
        html = render.build_html(CARD, "dark")
        self.assertIn("@font-face", html)
        self.assertIn("LP Sans", html)
        self.assertNotIn("antialiased", html, "antialiased 会让字变细")

    def test_chars_collected_from_all_fields(self):
        card = dict(
            CARD,
            title="标题甲",
            text="正文乙",
            translation="译文丙",
            comments=[{"author": "丁", "text": "评论戊", "likes": "1"}],
        )
        chars = render._text_chars(card)
        for ch in "标题甲正文乙译文丙丁评论戊":
            self.assertIn(ch, chars)


class TestArticleFont(unittest.TestCase):
    def test_article_html_embeds_font(self):
        article = {
            "title": "猫",
            "url": "https://zh.wikipedia.org/wiki/猫",
            "author": None,
            "image": None,
            "domain": "zh.wikipedia.org",
        }
        blocks = [{"level": 2, "title": "概述", "text": "猫是一种哺乳动物。"}]
        html = render.build_article_html(article, blocks, 1, 2, 0, "dark")
        self.assertIn("@font-face", html)
        self.assertIn("LP Sans", html)


class TestBrandAccent(unittest.TestCase):
    """品牌色在深浅主题下都要看得见。"""

    def test_black_brand_lightened_on_dark(self):
        self.assertNotEqual(render.accent_for("#000000", "dark"), "#000000")

    def test_black_brand_kept_on_light(self):
        self.assertEqual(render.accent_for("#000000", "light"), "#000000")

    def test_saturated_colors_untouched(self):
        for c in ("#ff0000", "#0066dc", "#9146ff", "#1db954"):
            self.assertEqual(render.accent_for(c, "dark"), c, c)
            self.assertEqual(render.accent_for(c, "light"), c, c)

    def test_invalid_color_falls_back(self):
        self.assertEqual(render.accent_for("", "dark"), "#7c5cff")
        self.assertEqual(render.accent_for("red", "dark"), "#7c5cff")

    def test_every_platform_has_valid_brand_color(self):
        import fetchers

        for key, (name, color) in fetchers.PLATFORMS.items():
            self.assertRegex(color, r"^#[0-9a-f]{6}$", f"{name} 颜色格式不对")
            for theme in ("dark", "light"):
                self.assertRegex(render.accent_for(color, theme), r"^#[0-9a-f]{6}$")

    def test_card_uses_adjusted_color(self):
        card = dict(CARD, color="#000000")
        self.assertIn("#949494", render.build_html(card, "dark"))
        self.assertIn("--accent: #000000", render.build_html(card, "light"))


class TestTranslationBlock(unittest.TestCase):
    def test_renders_translation_block(self):
        card = dict(CARD, translation="这是译文")
        html = render.build_html(card, "dark")
        self.assertIn('class="trans"', html)
        self.assertIn("这是译文", html)

    def test_no_block_without_translation(self):
        html = render.build_html(dict(CARD, translation=None), "dark")
        self.assertNotIn('class="trans"', html)


class TestT2iOptions(unittest.TestCase):
    def test_returns_full_page_jpeg(self):
        opt = render.t2i_options()
        self.assertEqual(opt["type"], "jpeg")
        self.assertTrue(opt["full_page"])
        self.assertGreaterEqual(opt["quality"], 90)


class TestCropImage(unittest.TestCase):
    def _make(self, w, h, box, bg=(12, 11, 22)):
        from PIL import Image

        im = Image.new("RGB", (w, h), bg)
        for x in range(box[0], box[2]):
            for y in range(box[1], box[3]):
                im.putpixel((x, y), (200, 60, 60))
        path = os.path.join(tempfile.mkdtemp(), "t.jpg")
        im.save(path, "JPEG", quality=95)
        return path

    def test_crops_uniform_border(self):
        from PIL import Image

        path = self._make(400, 300, (50, 40, 250, 160))
        render.crop_image(path, pad=0)
        with Image.open(path) as im:
            w, h = im.size
        self.assertLess(w, 400)
        self.assertLess(h, 300)
        self.assertGreaterEqual(w, 200)
        self.assertGreaterEqual(h, 120)

    def test_pad_keeps_margin(self):
        from PIL import Image

        path = self._make(400, 300, (50, 40, 250, 160))
        render.crop_image(path, pad=10)
        with Image.open(path) as im:
            w, h = im.size
        self.assertGreaterEqual(w, 220)
        self.assertGreaterEqual(h, 140)

    def test_all_background_is_noop(self):
        from PIL import Image

        path = self._make(200, 200, (0, 0, 0, 0))
        render.crop_image(path)
        with Image.open(path) as im:
            self.assertEqual(im.size, (200, 200))

    def test_missing_file_does_not_raise(self):
        self.assertEqual(
            render.crop_image("/tmp/definitely-not-here.jpg"),
            "/tmp/definitely-not-here.jpg",
        )


class TestMascot(unittest.TestCase):
    """看板娘：线上文转图和本地预览拿到同一份变量；图缺失时整块不画。"""

    def test_card_data_has_font_and_mascot(self):
        d = render.card_data(CARD, "dark")
        self.assertTrue(d["mascot"].startswith("data:image/webp;base64,"))
        self.assertIn("@font-face", d["font_css"])
        self.assertEqual(d["c"]["color"], render.accent_for("#000000", "dark"))
        self.assertTrue(d["t2i"])

    def test_article_data_has_mascot(self):
        d = render.article_data(
            {"title": "t", "url": "https://zh.wikipedia.org/wiki/t"},
            [{"title": "a", "level": 2, "text": "b"}],
            1,
            2,
        )
        self.assertTrue(d["mascot"])
        self.assertIn("@font-face", d["font_css"])

    def test_mascot_drawn(self):
        html = render.build_html(CARD, "dark")
        self.assertIn('class="neko"', html)
        self.assertIn('class="stage has-neko"', html)

    def test_no_mascot_file(self):
        old = render._MASCOT_URI[:]
        render._MASCOT_URI[:] = [""]
        try:
            html = render.build_html(CARD, "light")
            self.assertNotIn('class="neko"', html)
            self.assertNotIn('class="stage has-neko"', html)
            art = render.build_article_html({"title": "t"}, [], 1, 1)
            self.assertNotIn('class="neko"', art)
        finally:
            render._MASCOT_URI[:] = old

    def test_article_bubble_truncates_title(self):
        html = render.build_article_html({"title": "很长" * 20}, [], 1, 1)
        bubble = html.split('class="bubble"')[1].split("</div>")[0]
        self.assertIn("…", bubble)


if __name__ == "__main__":
    unittest.main()
