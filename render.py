"""把卡片字典变成 HTML，交给 AstrBot 的文转图服务出图，再裁掉多余留白。"""

import asyncio
import base64
import re
from functools import lru_cache
from pathlib import Path
from urllib.parse import unquote, urlsplit

import jinja2

from astrbot.api import logger

TEMPLATE = Path(__file__).parent / "templates" / "card.html"

# 徽章里的小图标（只用常见字体都有的字符）
ICONS = {
    "x": "X",
    "youtube": "▶",
    "reddit": "r",
    "github": "G",
    "bluesky": "B",
    "pixiv": "P",
    "steam": "S",
    "wikipedia": "W",
    "wikisource": "文",
    "tiktok": "♪",
    "spotify": "♫",
    "vimeo": "V",
    "soundcloud": "S",
    "instagram": "I",
    "threads": "@",
    "twitch": "T",
    "facebook": "f",
    "web": "↗",
    "dailymotion": "d",
    "niconico": "N",
    "zhihu": "知",
    "bilibili": "B",
    "douyin": "抖",
    "kuaishou": "快",
    "ixigua": "西",
    "vqq": "腾",
    "youku": "优",
    "iqiyi": "爱",
    "weibo": "微",
    "xiaohongshu": "书",
}

_env = jinja2.Environment(autoescape=True)


def _clip(text, n):
    if not text:
        return text
    text = str(text).strip()
    return text if len(text) <= n else text[:n].rstrip() + "…"


async def _data_uri(client, url, referer=None, max_bytes=6 * 1024 * 1024):
    if not url:
        return None
    try:
        headers = {"Referer": referer} if referer else {}
        async with client.stream("GET", url, headers=headers) as r:
            ctype = r.headers.get("content-type", "").split(";")[0].strip()
            if r.status_code != 200 or ctype not in {
                "image/jpeg",
                "image/png",
                "image/webp",
                "image/gif",
            }:
                return None
            content = bytearray()
            async for chunk in r.aiter_bytes(chunk_size=65536):
                content.extend(chunk)
                if len(content) > max_bytes:
                    return None
            return f"data:{ctype};base64," + base64.b64encode(content).decode()
    except Exception:
        return None


async def _image_info(client, url, referer=None, max_bytes=6 * 1024 * 1024):
    """下载图片，返回 (data URI, 宽, 高)。失败返回 (None, 0, 0)。"""
    uri = await _data_uri(client, url, referer, max_bytes)
    if not uri:
        return None, 0, 0
    try:
        import io

        from PIL import Image

        raw = base64.b64decode(uri.split(",", 1)[1])
        with Image.open(io.BytesIO(raw)) as im:
            if im.width * im.height > 20_000_000:
                return None, 0, 0
            return uri, im.size[0], im.size[1]
    except Exception:
        return None, 0, 0


def media_needs_stack(sizes, ratio=1.25):
    """竖图要纵向排列。

    多图版式用 object-fit: cover 把图裁成固定高度，竖图（高/宽 > 1.25，
    比如手机截图 1:2）会被上下切掉，所以这类卡片改成纵向堆叠、整张显示。
    """
    return any(h and w and h / w > ratio for w, h in sizes)


async def prepare(client, card, text_length=420, show_images=True, comments_mode=False):
    """下载图片、截断文字，返回可以直接套模板的卡片。

    comments_mode=True 是 /评论 指令用的评论卡：正文缩短、不放图片，评论放宽。
    """
    c = dict(card)
    c["comments_mode"] = comments_mode
    if comments_mode:
        show_images = False
        text_length = min(text_length, 120)
    # 有的图床（新浪、部分 CDN）不带 Referer 直接 403，默认用原页面地址当 Referer
    ref_url = urlsplit(c.get("referer") or c.get("url") or "")
    ref = f"{ref_url.scheme}://{ref_url.netloc}/" if ref_url.netloc else None
    avatar = (c.get("author") or {}).get("avatar")
    imgs = c.get("images") if show_images else []
    results = await asyncio.gather(
        _image_info(client, avatar, ref),
        *[_image_info(client, u, ref) for u in (imgs or [])[:4]],
    )
    if c.get("author"):
        c["author"] = dict(c["author"], avatar=results[0][0])
    pics = results[1:]
    c["images"] = [x[0] for x in pics if x[0]]
    c["media_tall"] = media_needs_stack([(w, h) for _, w, h in pics if w and h])
    c["title"] = _clip(c.get("title"), 140)
    c["text"] = _clip(c.get("text"), text_length)
    c["translation"] = _clip(c.get("translation"), text_length + 200)
    c["comments"] = [
        dict(x, text=_clip(x.get("text"), 300 if comments_mode else 140))
        for x in c.get("comments") or []
        if x.get("text")
    ]
    if c.get("quote"):
        c["quote"] = dict(c["quote"], text=_clip(c["quote"].get("text"), 200))
    host = urlsplit(c["url"]).hostname or ""
    c["domain"] = host.removeprefix("www.")
    # 页脚只显示域名和路径，去掉 www. 和结尾的斜杠
    short = unquote(c["url"].split("://", 1)[-1]).removeprefix("www.").rstrip("/")
    c["short_url"] = short if len(short) <= 64 else short[:63] + "…"
    c["icon"] = ICONS.get(c["platform"], "↗")
    if c.get("sensitive") and c.get("images"):
        c["blur"] = True
        c["note"] = c.get("note") or "平台标记的敏感内容"
    return c


ARTICLE = Path(__file__).parent / "templates" / "article.html"


async def prepare_article(client, article):
    """维基全文：首图转成 data URI，补上显示用的域名和短链接。"""
    a = dict(article)
    a["image"] = (await _image_info(client, a.get("image")))[0]
    a["domain"] = urlsplit(a["url"]).hostname or "wikipedia.org"
    short = unquote(a["url"].split("://", 1)[-1]).removeprefix("www.").rstrip("/")
    a["short_url"] = short if len(short) <= 70 else short[:69] + "…"
    return a


def article_data(article, blocks, no, total, hidden=0, theme="dark", t2i=True):
    """全文一页的模板变量；本地预览和文转图共用，保证两边出图一样。"""
    text = " ".join(
        f"{(b or {}).get('title') or ''} {(b or {}).get('text') or ''}"
        for b in (blocks or [])
    )
    font_card = {
        "title": article.get("title"),
        "text": text,
        "author": {"name": article.get("author")},
        "comments": [],
    }
    return {
        "a": article,
        "blocks": blocks,
        "no": no,
        "total": total,
        "hidden": hidden,
        "theme": "light" if theme == "light" else "dark",
        "t2i": t2i,
        "font_css": font_css(font_card),
        "mascot": mascot_uri(),
    }


def build_article_html(article, blocks, no, total, hidden=0, theme="dark"):
    tpl = _env.from_string(ARTICLE.read_text(encoding="utf-8"))
    return tpl.render(
        **article_data(article, blocks, no, total, hidden, theme, t2i=False)
    )


# 卡片顶上探出头的看板娘：已抠好透明底、只留到胸口（下面被卡片挡住），12KB 左右
MASCOT = Path(__file__).parent / "templates" / "mascot.webp"
_MASCOT_URI = []


def mascot_uri():
    """看板娘的 data URI；文件不在就返回空串，模板里会整块不画。"""
    if not _MASCOT_URI:
        try:
            _MASCOT_URI.append(
                "data:image/webp;base64,"
                + base64.b64encode(MASCOT.read_bytes()).decode()
            )
        except OSError:
            _MASCOT_URI.append("")
    return _MASCOT_URI[0]


FONT_DIR = Path(__file__).parent / "fonts"
# 只打包 400 / 700 两个字重，800、900 由浏览器合成，够用且体积可控
FONTS = (
    (FONT_DIR / "NotoSansSC-Regular.woff2", 400),
    (FONT_DIR / "NotoSansSC-Bold.woff2", 700),
)
FONT_FAMILY = "LP Sans"


def _text_chars(card):
    """收集这张卡片上会出现的所有字符，用来给字体做子集。"""
    a = card.get("author") or {}
    q = card.get("quote") or {}
    parts = [
        card.get("title"),
        card.get("text"),
        card.get("translation"),
        card.get("note"),
        card.get("platform_name"),
        card.get("short_url"),
        card.get("domain"),
        a.get("name"),
        a.get("handle"),
        q.get("author"),
        q.get("text"),
        " ".join(card.get("tags") or []),
        "".join(f"{k}{v}" for k, v in (card.get("stats") or [])),
        "".join(
            f"{c.get('author') or ''}{c.get('text') or ''}{c.get('likes') or ''}{c.get('time') or ''}"
            for c in (card.get("comments") or [])
        ),
    ]
    return "".join(sorted({ch for p in parts if p for ch in str(p)}))


@lru_cache(maxsize=40)
def _subset_b64(path, chars):
    """按用到的字符重新子集化字体，返回 base64。

    不同渲染机装的字体不一样，同一张卡会忽粗忽细、中文变宋体。
    把字体打进 HTML 就一致了；再按字符裁剪，体积从 700KB 降到几十 KB。
    没装 fonttools 时退回整份字体，效果一样只是请求大一点。
    """
    try:
        import io

        from fontTools import subset
        from fontTools.ttLib import TTFont

        # 使用 AstrBot logger 报告插件事件，不改动其他库的全局日志级别。

        opts = subset.Options()
        opts.flavor = "woff2"
        opts.desubroutinize = True
        with TTFont(str(path)) as font:
            sub = subset.Subsetter(options=opts)
            sub.populate(text=chars)
            sub.subset(font)
            font.flavor = "woff2"
            buf = io.BytesIO()
            font.save(buf)
        data = buf.getvalue()
    except Exception as e:  # 没装 fonttools / 字体损坏都走这里
        logger.debug(f"[LinkPreview] 字体子集化失败，改用整份字体：{e}")
        try:
            data = path.read_bytes()
        except OSError:
            return ""
    b64 = base64.b64encode(data).decode()
    return b64


def font_css(card):
    """生成内嵌字体的 @font-face 样式。"""
    chars = _text_chars(card) or "A"
    faces = []
    for path, weight in FONTS:
        if not path.exists():
            continue
        b64 = _subset_b64(path, chars)
        if not b64:
            continue
        faces.append(
            f'@font-face{{font-family:"{FONT_FAMILY}";font-style:normal;font-weight:{weight};'
            f'font-display:block;src:url(data:font/woff2;base64,{b64}) format("woff2")}}'
        )
    return "".join(faces)


def _luminance(hex_color):
    """相对亮度（WCAG 公式），用来判断品牌色在卡片背景上够不够显眼。"""

    def ch(v):
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4

    r, g, b = (int(hex_color[i : i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def accent_for(color, theme="dark"):
    """按主题修正品牌色：纯黑的品牌（X、GitHub、维基）在深色卡片上要调亮，
    接近白色的在浅色卡片上要压暗，否则那一条渐变和徽章就看不见了。
    """
    c = str(color or "").strip()
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", c):
        return "#7c5cff"
    lum = _luminance(c)
    rgb = [int(c[i : i + 2], 16) for i in (1, 3, 5)]
    if theme == "light":
        if lum > 0.75:
            rgb = [round(v * 0.55) for v in rgb]
    elif lum < 0.06:
        # 只有接近纯黑的品牌色才调亮；饱和色（如 Dailymotion 的蓝）本身就够显眼
        rgb = [round(v + (255 - v) * 0.58) for v in rgb]
    return "#%02x%02x%02x" % tuple(rgb)


def card_data(card, theme="dark", t2i=True):
    """卡片的模板变量：调过对比度的品牌色、内嵌字体、看板娘图。

    文转图服务拿到的是模板原文 + 这份变量，在远端渲染；本地 build_html 也用它，
    这样字体和配色在两条路径上都生效。
    """
    theme = "light" if theme == "light" else "dark"
    c = dict(card, color=accent_for(card.get("color"), theme))
    return {
        "c": c,
        "theme": theme,
        "t2i": t2i,
        "font_css": font_css(card),
        "mascot": mascot_uri(),
    }


def build_html(card, theme="dark", t2i=True):
    """渲染成 HTML 字符串。t2i=True 时套用文转图的版式（铺满 800 宽视口）。"""
    tpl = _env.from_string(TEMPLATE.read_text(encoding="utf-8"))
    return tpl.render(**card_data(card, theme, t2i))


# ---------------------------------------------------------------------------
# 文转图（AstrBot 的 html_render）：远端服务固定 800 宽视口、DPR 1，
# 忽略 device_scale_factor，高度会随内容延伸但不会小于 720。
# 所以模板里让卡片铺满 800 宽（body.t2i），出图后再裁掉多余留白。


def t2i_options():
    """交给 AstrBot 文转图服务的截图参数。"""
    return {"type": "jpeg", "quality": 92, "full_page": True}


def crop_image(path, pad=8, threshold=10):
    """裁掉四周与背景色相同的留白。

    远端视口高度固定 720，矮卡片下方会留一大片纯背景色；左右也可能有边距。
    这里按「与左上角背景色的差异」求包围盒，再留一点阴影边距。
    """
    from PIL import Image, ImageChops

    try:
        im = Image.open(path).convert("RGB")
    except (OSError, ValueError):
        return path
    w, h = im.size
    if w < 8 or h < 8:
        return path

    bg = im.getpixel((2, 2))
    diff = ImageChops.difference(im, Image.new("RGB", im.size, bg)).convert("L")
    mask = diff.point(lambda v: 255 if v > threshold else 0)
    box = mask.getbbox()
    if not box:
        return path

    left = max(0, box[0] - pad)
    top = max(0, box[1] - pad)
    right = min(w, box[2] + pad)
    bottom = min(h, box[3] + pad)
    if (left, top, right, bottom) == (0, 0, w, h):
        return path

    im.crop((left, top, right, bottom)).save(path, "JPEG", quality=92)
    return path
