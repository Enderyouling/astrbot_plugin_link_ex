"""各平台链接的信息抓取。

每个抓取函数返回一张「卡片」字典，由 render.py 统一画成图片：
    {
      "platform": "youtube", "platform_name": "YouTube", "color": "#ff0033",
      "url": 原链接, "title": 标题, "text": 正文,
      "author": {"name", "handle", "avatar"},   # avatar 为图片地址，渲染前会转成 data URI
      "images": [图片地址...], "video": bool, "duration": "3:32",
      "stats": [[名称, 数值], ...], "time": "2024-05-01 12:00", "tags": [...],
      "quote": {"author", "text"} | None, "sensitive": bool, "note": 附加说明,
      "comments": [{"author", "text", "likes", "time"}],   # 热门评论，拿不到就是空列表
    }
日志统一走 astrbot.api 的 logger，不再有标准库兜底。
"""

import asyncio
import ipaddress
from functools import lru_cache
import html as htmllib
import json
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import (
    parse_qsl,
    quote,
    unquote,
    urlencode,
    urljoin,
    urlsplit,
    urlunsplit,
)

import httpx

if __package__:
    from .safe_http import PreviewClient, PublicTransport
else:
    from safe_http import PreviewClient, PublicTransport

from astrbot.api import logger

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
CST = timezone(timedelta(hours=8))
# 维基要求 User-Agent 里带联系地址，不带会被 403
WIKI_UA = "NekoLinkPreview/1.0 (+https://github.com/EndermanMYR/astrbot_plugin_link_preview) httpx"
# Instagram 修复站只给「聊天软件抓取预览」的 User-Agent 返回内容
EMBED_BOT_UA = "Mozilla/5.0 (compatible; Discordbot/2.0; +https://discordapp.com)"

# 平台显示名和主色
PLATFORMS = {
    # 平台名 -> (显示名, 品牌色)。品牌色是纯黑的（X、GitHub、Wikipedia 等），
    # 渲染时会按主题自动调亮/调暗，保证在深色卡片上看得见。
    "x": ("X", "#000000"),
    "youtube": ("YouTube", "#ff0000"),
    "reddit": ("Reddit", "#ff4500"),
    "github": ("GitHub", "#181717"),
    "bluesky": ("Bluesky", "#0085ff"),
    "pixiv": ("pixiv", "#0096fa"),
    "steam": ("Steam", "#66c0f4"),
    "wikipedia": ("Wikipedia", "#000000"),
    "wikisource": ("维基文库", "#000000"),
    "tiktok": ("TikTok", "#fe2c55"),
    "spotify": ("Spotify", "#1db954"),
    "vimeo": ("Vimeo", "#1ab7ea"),
    "soundcloud": ("SoundCloud", "#ff5500"),
    "instagram": ("Instagram", "#e4405f"),
    "threads": ("Threads", "#000000"),
    "twitch": ("Twitch", "#9146ff"),
    "facebook": ("Facebook", "#1877f2"),
    "dailymotion": ("Dailymotion", "#0066dc"),
    "niconico": ("niconico", "#252525"),
    "web": ("网页", "#7c5cff"),
    "bilibili": ("哔哩哔哩", "#fb7299"),
    "douyin": ("抖音", "#fe2c55"),
    "xiaohongshu": ("小红书", "#ff2442"),
    "weibo": ("微博", "#e6162d"),
    "zhihu": ("知乎", "#0084ff"),
    "kuaishou": ("快手", "#ff4906"),
    "ixigua": ("西瓜视频", "#ff5a1f"),
    "vqq": ("腾讯视频", "#00a4ff"),
    "youku": ("优酷", "#1ba5e0"),
    "iqiyi": ("爱奇艺", "#00be06"),
}

# 只取元信息（OpenGraph）的站点：域名 -> 平台 key
OG_SITES = {
    "threads.net": "threads",
    "threads.com": "threads",
    "twitch.tv": "twitch",
    "facebook.com": "facebook",
    "fb.watch": "facebook",
}

# 链接识别：平台 key -> 正则（按顺序匹配，先到先得）
LINK_PATTERNS = [
    (
        "x",
        re.compile(
            r"https?://(?:www\.|mobile\.)?(?:x|twitter|fxtwitter|vxtwitter|fixupx|fixvx)\.com/"
            r"(?:[A-Za-z0-9_]{1,15}|i(?:/web)?)/status(?:es)?/(\d{1,19})",
            re.I,
        ),
    ),
    (
        "youtube",
        re.compile(
            r"https?://(?:www\.|m\.|music\.)?(?:youtube\.com/(?:watch\?(?:[^\s#]*&)?v=|shorts/|live/|embed/)"
            r"|youtu\.be/)([A-Za-z0-9_-]{11})",
            re.I,
        ),
    ),
    (
        "reddit",
        re.compile(
            r"https?://(?:www\.|old\.|new\.|np\.)?(?:reddit\.com/r/[A-Za-z0-9_]+/(?:comments|s)/[A-Za-z0-9_]+[^\s]*"
            r"|redd\.it/[A-Za-z0-9]+)",
            re.I,
        ),
    ),
    (
        "github",
        re.compile(
            r"https?://(?:www\.)?github\.com/([A-Za-z0-9-]{1,39})(?:/([A-Za-z0-9._-]{1,100})"
            r"(?:/(issues|pull)/(\d+))?)?",
            re.I,
        ),
    ),
    (
        "bluesky",
        re.compile(r"https?://bsky\.app/profile/([^/\s]+)/post/([A-Za-z0-9]+)", re.I),
    ),
    (
        "pixiv",
        re.compile(r"https?://(?:www\.)?pixiv\.net/(?:en/)?artworks/(\d+)", re.I),
    ),
    ("steam", re.compile(r"https?://store\.steampowered\.com/app/(\d+)", re.I)),
    (
        "wikipedia",
        re.compile(
            r"https?://([a-z-]{2,12})\.(?:m\.)?wikipedia\.org/wiki/([^\s?#<>\"']+)",
            re.I,
        ),
    ),
    (
        "wikisource",
        re.compile(
            r"https?://([a-z-]{2,12})\.(?:m\.)?wikisource\.org/wiki/([^\s?#<>\"']+)",
            re.I,
        ),
    ),
    (
        "tiktok",
        re.compile(r"https?://(?:www\.|vm\.|vt\.|m\.)?tiktok\.com/[^\s<>\"']+", re.I),
    ),
    (
        "instagram",
        re.compile(
            r"https?://(?:www\.)?instagram\.com/(?:[A-Za-z0-9_.]+/)?(p|reels?|tv)/([A-Za-z0-9_-]+)",
            re.I,
        ),
    ),
    (
        "dailymotion",
        re.compile(
            r"https?://(?:www\.)?(?:dailymotion\.com/video/|dai\.ly/)([A-Za-z0-9]+)",
            re.I,
        ),
    ),
    (
        "niconico",
        re.compile(
            r"https?://(?:www\.|sp\.)?(?:nicovideo\.jp/watch/|nico\.ms/)((?:sm|so|nm)\d+)",
            re.I,
        ),
    ),
    (
        "spotify",
        re.compile(
            r"https?://open\.spotify\.com/(?:intl-[a-z-]+/)?(?:track|album|playlist|artist|episode|show)/[A-Za-z0-9]+[^\s<>\"']*",
            re.I,
        ),
    ),
    ("vimeo", re.compile(r"https?://(?:www\.)?vimeo\.com/\d+[^\s<>\"']*", re.I)),
    (
        "soundcloud",
        re.compile(
            r"https?://(?:www\.|m\.)?soundcloud\.com/[^\s/<>\"']+/[^\s<>\"']+", re.I
        ),
    ),
    (
        "og",
        re.compile(
            r"https?://(?:www\.|m\.)?(?:threads\.(?:net|com)|twitch\.tv|facebook\.com|fb\.watch)/[^\s<>\"']+",
            re.I,
        ),
    ),
    ("kuaishou", re.compile(r"https?://(?:www\.|v\.)?kuaishou\.com/[^\s<>\"']+", re.I)),
    ("ixigua", re.compile(r"https?://(?:www\.)?ixigua\.com/[^\s<>\"']+", re.I)),
    ("vqq", re.compile(r"https?://v\.qq\.com/[^\s<>\"']+", re.I)),
    ("youku", re.compile(r"https?://(?:www\.|v\.)?youku\.com/[^\s<>\"']+", re.I)),
    ("iqiyi", re.compile(r"https?://(?:www\.)?iqiyi\.com/[^\s<>\"']+", re.I)),
]

# Append to preserve the existing fetchers' positional pattern references.
LINK_PATTERNS += [
    (
        "bilibili",
        re.compile(
            r"https?://(?:(?:www\.|m\.)?bilibili\.com/video/(?:BV[0-9A-Za-z]{10}|av\d+)(?:[/?#]|$)|b23\.tv/[0-9A-Za-z]+(?:[/?#]|$))",
            re.I,
        ),
    ),
    (
        "douyin",
        re.compile(
            r"https?://(?:(?:www\.|m\.)?douyin\.com/(?:video|note)/\d+(?:[/?#]|$)|v\.douyin\.com/[0-9A-Za-z_-]+(?:[/?#]|$)|www\.iesdouyin\.com/share/video/\d+(?:[/?#]|$))",
            re.I,
        ),
    ),
    (
        "xiaohongshu",
        re.compile(
            r"https?://(?:(?:www\.|m\.)?xiaohongshu\.com/(?:explore|discovery/item)/[0-9a-f]+(?:[/?#]|$)|xhslink\.com/[0-9A-Za-z/]+(?:[?#]|$))",
            re.I,
        ),
    ),
    (
        "weibo",
        re.compile(
            r"https?://(?:(?:www\.)?weibo\.com/\d+/[0-9A-Za-z]+(?:[/?#]|$)|m\.weibo\.cn/(?:detail|status)/[0-9A-Za-z]+(?:[/?#]|$))",
            re.I,
        ),
    ),
    (
        "zhihu",
        re.compile(
            r"https?://(?:(?:www\.)?zhihu\.com/(?:question/\d+(?:/answer/\d+)?|answer/\d+|zvideo/\d+)(?:[/?#]|$)|zhuanlan\.zhihu\.com/p/\d+(?:[/?#]|$))",
            re.I,
        ),
    ),
]

LINK_PATTERNS += [
    (
        "weibo",
        re.compile(
            r"https?://(?:weibo\.com/tv/show/|video\.weibo\.com/show\?fid=)[0-9A-Za-z:]+",
            re.I,
        ),
    )
]
LINK_PATTERNS += [("web", re.compile(r"https?://[^\s<>\"']+", re.I))]

DOMESTIC_HOSTS = {
    "bilibili": {"www.bilibili.com", "m.bilibili.com", "bilibili.com", "b23.tv"},
    "douyin": {
        "www.douyin.com",
        "m.douyin.com",
        "douyin.com",
        "v.douyin.com",
        "www.iesdouyin.com",
    },
    "xiaohongshu": {
        "www.xiaohongshu.com",
        "m.xiaohongshu.com",
        "xiaohongshu.com",
        "xhslink.com",
    },
    "weibo": {"weibo.com", "www.weibo.com", "m.weibo.cn", "video.weibo.com"},
    "zhihu": {"www.zhihu.com", "zhihu.com", "zhuanlan.zhihu.com"},
    "kuaishou": {"www.kuaishou.com", "v.kuaishou.com", "kuaishou.com"},
    "ixigua": {"www.ixigua.com", "ixigua.com"},
    "vqq": {"v.qq.com"},
    "youku": {"v.youku.com", "www.youku.com", "youku.com"},
    "iqiyi": {"www.iqiyi.com", "iqiyi.com"},
}

# GitHub 一级路径里不是用户名的保留词
GITHUB_RESERVED = {
    "about",
    "pricing",
    "features",
    "topics",
    "trending",
    "explore",
    "marketplace",
    "orgs",
    "settings",
    "login",
    "join",
    "sponsors",
    "collections",
    "notifications",
    "search",
    "site",
    "security",
    "enterprise",
    "apps",
    "codespaces",
    "issues",
    "pulls",
}

URL_RE = re.compile(r"https?://[^\s<>\"'\]\[，。！？、）（]+", re.I)


class FetchError(Exception):
    pass


# 各平台分享链接里带的跟踪参数，比较「是不是同一条」时要忽略
TRACKING_PARAMS = {
    "a",
    "s",
    "t",
    "ref",
    "ref_src",
    "ref_url",
    "si",
    "igshid",
    "share",
    "share_id",
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "feature",
    "fbclid",
    "gclid",
    "spm",
    "from",
    "share_source",
}
# 同一个帖子的不同域名，归一到一个，避免同一条链接被预览两次
HOST_ALIASES = {
    "twitter.com": "x.com",
    "mobile.twitter.com": "x.com",
    "vxtwitter.com": "x.com",
    "fxtwitter.com": "x.com",
    "fixupx.com": "x.com",
    "fixvx.com": "x.com",
    "youtu.be": "youtube.com",
    "m.youtube.com": "youtube.com",
    "music.youtube.com": "youtube.com",
}


def canonical_url(url):
    """把链接归一成「同一个帖子」的形式：去跟踪参数、去锚点、统一镜像域名。

    QQ 分享卡片里的链接常带 ?a=xxx&s=20，正文里又是干净的，
    不归一的话同一条帖子会被识别成两条、出两张卡。
    """
    try:
        u = urlsplit(str(url or "").strip())
    except ValueError:
        return str(url or "")
    host = (u.hostname or "").lower()
    host = HOST_ALIASES.get(host, host)
    if host.startswith("www."):
        host = host[4:]
    query = [
        (k, v)
        for k, v in parse_qsl(u.query, keep_blank_values=True)
        if k.lower() not in TRACKING_PARAMS
    ]
    path = u.path.rstrip("/") or "/"
    return urlunsplit(("https", host, path, urlencode(query), ""))


# 群里常有人直接发「www.bilibili.com」这种不带协议的裸域名，也要能认出来。
# 只认常见顶级域，避免把 1.2.3、file.txt、a@b.com 之类误判成网址。
COMMON_TLDS = {
    "com",
    "net",
    "org",
    "edu",
    "gov",
    "mil",
    "int",
    "info",
    "biz",
    "name",
    "pro",
    "mobi",
    "asia",
    "tel",
    "travel",
    "jobs",
    "cat",
    "coop",
    "aero",
    "museum",
    "app",
    "dev",
    "page",
    "tech",
    "cloud",
    "site",
    "online",
    "shop",
    "store",
    "club",
    "xyz",
    "top",
    "vip",
    "win",
    "link",
    "live",
    "news",
    "blog",
    "wiki",
    "space",
    "website",
    "press",
    "media",
    "video",
    "music",
    "photo",
    "pics",
    "art",
    "design",
    "fun",
    "icu",
    "work",
    "today",
    "world",
    "life",
    "zone",
    "cn",
    "jp",
    "kr",
    "tw",
    "hk",
    "mo",
    "sg",
    "in",
    "id",
    "th",
    "vn",
    "ph",
    "my",
    "uk",
    "de",
    "fr",
    "it",
    "es",
    "nl",
    "be",
    "ch",
    "at",
    "se",
    "no",
    "fi",
    "dk",
    "pl",
    "cz",
    "hu",
    "ro",
    "gr",
    "pt",
    "ie",
    "ru",
    "ua",
    "by",
    "kz",
    "tr",
    "il",
    "ae",
    "sa",
    "us",
    "ca",
    "mx",
    "br",
    "ar",
    "cl",
    "pe",
    "ve",
    "au",
    "nz",
    "za",
    "eg",
    "ma",
    "ng",
    "ke",
    "tv",
    "cc",
    "me",
    "ly",
    "gg",
    "to",
    "fm",
    "am",
    "ws",
    "la",
    "sh",
    "ac",
}
# 中文域名（IDN）：标签里可以是汉字，顶级域也是汉字（.中国 .公司 .网络 …）
CJK_TLDS = {
    "中国",
    "中國",
    "公司",
    "网络",
    "網絡",
    "网址",
    "網址",
    "网站",
    "網站",
    "商城",
    "商店",
    "商标",
    "商標",
    "在线",
    "在線",
    "中文网",
    "中文網",
    "集团",
    "集團",
    "企业",
    "企業",
    "世界",
    "游戏",
    "遊戲",
    "娱乐",
    "娛樂",
    "音乐",
    "音樂",
    "购物",
    "購物",
    "新闻",
    "新聞",
    "公益",
    "政务",
    "政務",
    "政府",
    "机构",
    "機構",
    "组织",
    "組織",
    "教育",
    "招聘",
    "手机",
    "手機",
    "时尚",
    "時尚",
    "汽车",
    "汽車",
    "博客",
    "微博",
    "我爱你",
    "我愛你",
    "美食",
    "酒店",
    "旅游",
    "旅遊",
    "健康",
    "广东",
    "廣東",
    "佛山",
    "信息",
    "資訊",
    "移动",
    "移動",
    "网店",
    "網店",
    "门户",
    "門戶",
    "餐厅",
    "餐廳",
    "家装",
    "家裝",
    "珠宝",
    "珠寶",
    "手表",
    "手錶",
    "台湾",
    "台灣",
    "香港",
    "澳门",
    "澳門",
    "新加坡",
    "酷",
}
# 域名标签：ASCII 版和「允许汉字」版分开写。
# 分开的原因：中文文本里汉字和域名常连在一起（「看www.bilibili.com这个」），
# 如果只用一个允许汉字的正则，它会把「看www.bilibili.com」整个吃进去。
_LABEL_ASCII = r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
_LABEL_IDN = r"[A-Za-z0-9\u4e00-\u9fff](?:[A-Za-z0-9\u4e00-\u9fff-]{0,61}[A-Za-z0-9\u4e00-\u9fff])?"
_TAIL = r"(?::\d{2,5})?(/[^\s<>\"'，。！？、）】」]*)?"


def normalize_tlds(values):
    """配置里填的额外顶级域：去掉前导点、转小写、去重。"""
    out = []
    for v in values or []:
        t = str(v or "").strip().lower().lstrip(".")
        if t and re.fullmatch(r"[a-z0-9\u4e00-\u9fff-]{1,24}", t):
            out.append(t)
    return tuple(sorted(set(out)))


def _tld_alt(tlds):
    # 按长度倒序内联进正则，这样「中文.中国这个」能停在「中国」，
    # 而不是贪婪吃到「中国这个」再被判非法
    return "|".join(re.escape(t) for t in sorted(tlds, key=len, reverse=True))


@lru_cache(maxsize=16)
def bare_patterns(extra=()):
    """按「额外顶级域」生成两条裸域名正则，结果缓存。

    ASCII 域名和中文域名分开：中文文本里汉字和域名常连在一起
    （「看www.bilibili.com这个」），用一条允许汉字的正则会把前面的汉字吃进去。
    """
    extra = set(extra)
    ascii_tlds = COMMON_TLDS | {t for t in extra if t.isascii()}
    any_tlds = COMMON_TLDS | CJK_TLDS | extra
    ascii_re = re.compile(
        rf"(?<![A-Za-z0-9_@./:%-])"
        rf"((?:{_LABEL_ASCII}\.)+(?:xn--[A-Za-z0-9]{{2,30}}|{_tld_alt(ascii_tlds)})){_TAIL}",
        re.I,
    )
    idn_re = re.compile(
        rf"(?<![A-Za-z0-9_@./:%-])"
        rf"((?:{_LABEL_IDN}\.)+(?:xn--[A-Za-z0-9]{{2,30}}|{_tld_alt(any_tlds)})){_TAIL}",
        re.I,
    )
    return ascii_re, idn_re


def _is_cjk(ch):
    return "\u4e00" <= ch <= "\u9fff"


def _cut_in_label(text, end):
    """匹配后面还接着字母/数字/连字符，说明域名被截断了。

    比如 example.mov 会先匹配到 example.mo（澳门），后面的 v 说明这不是完整域名。
    """
    if end >= len(text):
        return False
    ch = text[end]
    return ch.isascii() and (ch.isalnum() or ch == "-")


def candidate_urls(text, extra_tlds=None):
    """文本里所有候选链接，按出现顺序返回。

    带协议的优先；没协议的裸域名补上 https://，但要排除落在已知链接内部、
    以及顶级域不在白名单里的（1.2.3、file.txt、a@b.com 这类）。
    extra_tlds 是配置里补充的顶级域，用来认内置列表之外的域名。
    """
    ascii_re, idn_re = bare_patterns(normalize_tlds(extra_tlds))
    text = text or ""
    spans = []
    for m in URL_RE.finditer(text):
        url = m.group(0).rstrip(".,;:!?）】」")
        while url.endswith(")") and url.count("(") < url.count(")"):
            url = url[:-1]
        spans.append((m.start(), m.start() + len(url), url))

    out = [(start, url) for start, _, url in spans]
    taken = [(a, b) for a, b, _ in spans]

    # 先认纯 ASCII 域名：中文句子里的 www.xxx.com 不会被前面的汉字带偏
    for m in ascii_re.finditer(text):
        start, end = m.span()
        if _cut_in_label(text, end):
            continue
        if any(a < end and start < b for a, b in taken):
            continue
        out.append((start, "https://" + m.group(0)))
        taken.append((start, end))

    # 再认中文域名。夹在中文句子里没法分词（「我买了个中文.中国域名」到底哪几个字
    # 是域名？），所以要求前后都是非汉字边界，宁可不认也不抓一个错的域名回来
    for m in idn_re.finditer(text):
        start, end = m.span()
        domain = m.group(1)
        if not any(_is_cjk(c) for c in domain):
            continue
        if _cut_in_label(text, end):
            continue
        if any(a < end and start < b for a, b in taken):
            continue
        before = text[start - 1] if start else ""
        after = text[start + len(domain)] if start + len(domain) < len(text) else ""
        if (before and _is_cjk(before)) or (after and _is_cjk(after)):
            continue
        out.append((start, "https://" + m.group(0)))
        taken.append((start, end))

    out.sort(key=lambda x: x[0])
    return [url for _, url in out]


# 通用网页预览要挡掉的目标：本机/内网地址（避免被当成内网探针）、直链文件
_PRIVATE_HOST_RE = re.compile(
    r"^(?:localhost|127\.\d+\.\d+\.\d+|10\.\d+\.\d+\.\d+|192\.168\.\d+\.\d+"
    r"|172\.(?:1[6-9]|2\d|3[01])\.\d+\.\d+|169\.254\.\d+\.\d+|0\.0\.0\.0|::1)$",
    re.I,
)
_PRIVATE_SUFFIX = (".local", ".internal", ".lan", ".localhost", ".home.arpa")
_FILE_EXT_RE = re.compile(
    r"\.(?:jpe?g|png|gif|webp|bmp|svg|ico|tiff?|heic"
    r"|mp4|m4v|mov|avi|mkv|webm|flv|wmv|m3u8"
    r"|mp3|m4a|wav|flac|aac|ogg|opus"
    r"|zip|rar|7z|tar|gz|bz2|xz|apk|exe|msi|dmg|pkg|deb|rpm|iso|bin|torrent"
    r"|pdf|docx?|xlsx?|pptx?|epub|mobi|css|js|json|xml|csv|txt)$",
    re.I,
)


def is_previewable_web(url):
    """普通网页能不能预览：只收 http(s)、公网域名、看起来是页面的路径。"""
    try:
        u = urlsplit(str(url or "").strip())
    except ValueError:
        return False
    if u.scheme.lower() not in ("http", "https"):
        return False
    host = (u.hostname or "").strip("[]").lower()
    if u.username or u.password or not host or "." not in host:
        return False
    try:
        ip = ipaddress.ip_address(host)
        if not ip.is_global or ip.is_multicast:
            return False
    except ValueError:
        pass
    if _PRIVATE_HOST_RE.match(host) or host.endswith(_PRIVATE_SUFFIX):
        return False
    if _FILE_EXT_RE.search(u.path or ""):
        return False
    return True


def _web_blocked(host, blocked):
    """域名黑名单：example.com 也挡 sub.example.com。"""
    h = (host or "").lower()
    if h.startswith("www."):
        h = h[4:]
    for item in blocked or []:
        b = str(item or "").strip().lower().lstrip("@")
        if b.startswith("www."):
            b = b[4:]
        if b and (h == b or h.endswith("." + b)):
            return True
    return False


def find_links(text, enabled, limit=3, web_block=None, extra_tlds=None):
    """从文本里找出可预览的链接，返回 [(平台 key, 链接)]，同一链接只取一次。

    没被任何平台匹配到的 http(s) 链接会归到 "web"（通用 OpenGraph 预览），
    但内网地址、直链文件、黑名单域名会被跳过。
    """
    found, seen = [], set()
    for url in candidate_urls((text or "")[:16000], extra_tlds):
        try:
            parsed = urlsplit(url)
            if (
                parsed.username
                or parsed.password
                or _web_blocked(parsed.hostname, web_block)
            ):
                continue
        except ValueError:
            continue
        for key, pat in LINK_PATTERNS:
            m = pat.match(url)
            if not m:
                continue
            platform = OG_SITES.get(_host(url), "web") if key == "og" else key
            if platform == "github" and m.group(1).lower() in GITHUB_RESERVED:
                break
            if platform == "web" and (
                not is_previewable_web(url) or _web_blocked(_host(url), web_block)
            ):
                break
            ident = "|".join(g for g in m.groups() if g)
            key = (platform, ident) if ident else (platform, canonical_url(url))
            if enabled.get(platform, False) and key not in seen:
                seen.add(key)
                found.append((platform, url))
            break
        if len(found) >= limit:
            break
    return found


def _host(url):
    h = urlsplit(url).hostname or ""
    for prefix in ("www.", "m.", "mobile."):
        if h.startswith(prefix):
            h = h[len(prefix) :]
    return h


def compact(n):
    """数字缩写：12345 -> 1.2万。"""
    try:
        n = int(n)
    except (TypeError, ValueError):
        return None
    if n >= 100_000_000:
        return f"{n / 100_000_000:.1f}".rstrip("0").rstrip(".") + "亿"
    if n >= 10_000:
        return f"{n / 10_000:.1f}".rstrip("0").rstrip(".") + "万"
    return f"{n:,}"


def fmt_time(value):
    """时间戳 / ISO 字符串 -> 北京时间 'YYYY-MM-DD HH:MM'。"""
    if value in (None, ""):
        return None
    try:
        if isinstance(value, (int, float)) or str(value).isdigit():
            dt = datetime.fromtimestamp(int(value), tz=timezone.utc)
        else:
            s = str(value).strip().replace("Z", "+00:00")
            dt = datetime.fromisoformat(s) if "T" in s or "-" in s[:10] else None
            if dt is None:
                return str(value)
            if dt.tzinfo is None:
                return (
                    dt.strftime("%Y-%m-%d")
                    if len(s) <= 10
                    else dt.strftime("%Y-%m-%d %H:%M")
                )
        return dt.astimezone(CST).strftime("%Y-%m-%d %H:%M")
    except (ValueError, OSError, OverflowError):
        return str(value)


def duration(seconds):
    try:
        s = int(seconds)
    except (TypeError, ValueError):
        return None
    if s <= 0:
        return None
    h, rem = divmod(s, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


CJK_RE = re.compile(r"[\u4e00-\u9fff]")
KANA_RE = re.compile(r"[\u3040-\u30ff]")
HANGUL_RE = re.compile(r"[\uac00-\ud7af]")
LATIN_RE = re.compile(r"[A-Za-z]")


def needs_translation(text, min_latin=12):
    """判断一段文字要不要翻译成中文。

    日文（有假名）、韩文（有谚文）一律要翻；纯英文按拉丁字母数量判断；
    中文为主的正文不翻，免得白烧一次模型调用。
    """
    t = str(text or "")
    # 假名/谚文先判，短句（「안녕하세요」）也要翻
    if KANA_RE.search(t) or HANGUL_RE.search(t):
        return True
    if len(t) < 6:
        return False
    han = len(CJK_RE.findall(t))
    latin = len(LATIN_RE.findall(t))
    if han == 0:
        return latin >= min_latin
    return latin >= min_latin and latin > han


def flatten(text):
    """评论正文压成一行：X 的回复里常有多行和空行，原样渲染会在卡片上撑出大片空白。"""
    return re.sub(r"\s+", " ", str(text or "")).strip()


def stat(label, value):
    if value is None or value == "":
        return None
    v = (
        compact(value)
        if isinstance(value, (int, float)) or str(value).isdigit()
        else value
    )
    return [label, v]


def card(platform, url, **kw):
    name, color = PLATFORMS.get(platform, PLATFORMS["web"])
    c = {
        "platform": platform,
        "platform_name": name,
        "color": color,
        "url": url,
        "title": None,
        "text": None,
        "author": None,
        "images": [],
        "video": False,
        "duration": None,
        "stats": [],
        "time": None,
        "tags": [],
        "quote": None,
        "sensitive": False,
        "note": None,
        "comments": [],
    }
    c.update(kw)
    c["stats"] = [s for s in c["stats"] if s]
    return c


# ---------------------------------------------------------------------------
# 通用：OpenGraph
# ---------------------------------------------------------------------------

META_RE = re.compile(r"<meta\s+[^>]*>", re.I)
ATTR_RE = re.compile(r'([a-zA-Z:_-]+)\s*=\s*("([^"]*)"|\'([^\']*)\')')


def parse_meta(page):
    meta = {}
    for tag in META_RE.findall(page[:600_000]):
        attrs = {
            m.group(1).lower(): (m.group(3) if m.group(3) is not None else m.group(4))
            for m in ATTR_RE.finditer(tag)
        }
        key = (attrs.get("property") or attrs.get("name") or "").lower()
        if key and "content" in attrs and key not in meta:
            meta[key] = htmllib.unescape(attrs["content"]).strip()
    t = re.search(r"<title[^>]*>(.*?)</title>", page[:200_000], re.I | re.S)
    if t:
        meta.setdefault("title", htmllib.unescape(t.group(1)).strip())
    return meta


SITE_SPLIT_RE = re.compile(r"\s+[-–—|·_]\s+|\s*[|｜]\s*")
# 有些页面（B 站）把模板变量原样写进 description：「视频播放量 {$0}」
PLACEHOLDER_RE = re.compile(r"\{\$\d+\}")


def clean_site(name):
    """站点名压短：太长的按分隔符取前半段。"""
    s = flatten(name)
    if not s:
        return ""
    head = SITE_SPLIT_RE.split(s, 1)[0].strip()
    if head and head != s:
        s = head
    return s[:40]


def pretty_host(host):
    """punycode 域名转回中文显示：xn--fiqs8s -> 中国。转不了就原样返回。"""
    h = str(host or "").strip().rstrip(".")
    if "xn--" not in h.lower():
        return h
    try:
        return h.encode("ascii").decode("idna")
    except (UnicodeError, ValueError):
        return h


def clean_desc(text):
    """页面描述：压成一行；模板变量没渲染的（{$0}）直接丢掉。"""
    if not text:
        return None
    t = flatten(text)
    return None if PLACEHOLDER_RE.search(t) else t


async def get_html(client, url, html_only=False, max_bytes=8 * 1024 * 1024, **kw):
    r = await client.get(url, **kw)
    if r.status_code >= 400:
        raise FetchError(f"HTTP {r.status_code}")
    if html_only:
        # 有的链接看着像网页，其实是图片/压缩包，抓回来也解析不出东西
        ctype = (r.headers.get("content-type") or "").lower()
        if ctype and not (ctype.startswith("text/") or "xhtml" in ctype):
            raise FetchError(f"不是网页（{ctype.split(';')[0].strip()}）")
        if len(r.content) > max_bytes:
            raise FetchError("页面太大")
    return r.text, str(r.url)


LINK_TAG_RE = re.compile(r"<link\s+[^>]*>", re.I)


def _link_href(page, rels):
    """从 <link rel="..."> 里取 href（favicon 之类）。"""
    for tag in LINK_TAG_RE.findall(page[:300_000]):
        attrs = {
            m.group(1).lower(): (m.group(3) if m.group(3) is not None else m.group(4))
            for m in ATTR_RE.finditer(tag)
        }
        rel = (attrs.get("rel") or "").lower()
        if attrs.get("href") and any(r in rel for r in rels):
            return htmllib.unescape(attrs["href"]).strip()
    return None


async def fetch_og(client, platform, url):
    """通用网页 / 只提供 OpenGraph 的站点。

    og:image 常常是相对路径，要按最终 URL 补全；站点名和 favicon 拿来当「作者」，
    卡片才不至于只剩一行标题。
    """
    page, final = await get_html(client, url, html_only=True)
    m = parse_meta(page)
    title = m.get("og:title") or m.get("twitter:title") or m.get("title")
    desc = (
        m.get("og:description") or m.get("twitter:description") or m.get("description")
    )
    if not title:
        raise FetchError("页面没有可用的标题信息")
    title = flatten(title)
    desc = clean_desc(desc)
    # 被登录墙挡住时只能拿到站点名，这种卡片没有意义，直接放弃
    generic = {
        PLATFORMS.get(platform, PLATFORMS["web"])[0].lower(),
        "instagram",
        "tiktok",
        "threads",
        "facebook",
        "log in",
        "login",
        "sign in",
        "登录",
    }
    if title.strip().lower() in generic and not (
        desc and desc.strip().lower() not in generic
    ):
        raise FetchError("页面需要登录，拿不到内容")
    image = (
        m.get("og:image")
        or m.get("og:image:secure_url")
        or m.get("twitter:image")
        or m.get("twitter:image:src")
    )
    if image:
        image = urljoin(final, image)
    c = card(
        platform,
        url,
        title=title,
        text=desc,
        images=[image] if image else [],
        video=(m.get("og:type") or "").startswith("video"),
    )

    if platform == "web":
        host = pretty_host(_host(final))
        site = clean_site(m.get("og:site_name"))
        # 有的站点把 punycode 写进 og:site_name，直接显示是一串 xn--，不如用域名
        if not site or "xn--" in site.lower():
            site = host
        c["platform_name"] = site[:24]
        icon = _link_href(page, ("icon",)) or _link_href(page, ("image_src",))
        # 徽章已经显示站名了，作者行放域名，免得同一句话出现两次
        c["author"] = {
            "name": host,
            "handle": None,
            "avatar": urljoin(final, icon) if icon else None,
            "bio": None,
        }
        # 只认发布时间：首页的 og:updated_time 是「最后更新」，当发布时间显示很怪
        c["time"] = fmt_time(
            m.get("article:published_time") or m.get("article:modified_time")
        )
        tags = m.get("article:tag")
        if tags:
            c["tags"] = [t.strip() for t in str(tags).split(",") if t.strip()][:3]
    elif m.get("og:site_name"):
        c["platform_name"] = m["og:site_name"]
    return c


# ---------------------------------------------------------------------------
# X / Twitter：fxtwitter 公共接口
# ---------------------------------------------------------------------------


async def _x_card(client, url, tid):
    """主数据源：fxtwitter 公开接口，能拿到配图、头像、引用推。"""
    r = await client.get(f"https://api.fxtwitter.com/status/{tid}")
    data = r.json() if r.status_code == 200 else {}
    t = data.get("tweet")
    if not t:
        raise FetchError(data.get("message") or f"HTTP {r.status_code}")
    a = t.get("author") or {}
    media = t.get("media") or {}
    images, is_video, dur = [], False, None
    for p in media.get("photos") or []:
        images.append(p.get("url"))
    for v in media.get("videos") or []:
        if v.get("thumbnail_url"):
            images.append(v["thumbnail_url"])
        is_video = True
        dur = dur or duration(v.get("duration"))
    q = t.get("quote")
    quote_block = None
    if q:
        qa = q.get("author") or {}
        quote_block = {
            "author": f"{qa.get('name', '')} @{qa.get('screen_name', '')}",
            "text": q.get("text") or "",
        }
    return card(
        "x",
        url,
        text=t.get("text") or "",
        # bio 不显示在卡片上，只用来按账号屏蔽（简介里带敏感词的账号整条不发）
        author={
            "name": a.get("name"),
            "handle": "@" + (a.get("screen_name") or ""),
            "avatar": a.get("avatar_url"),
            "bio": " ".join(x for x in (a.get("description"), a.get("location")) if x),
        },
        images=images[:4],
        video=is_video and not media.get("photos"),
        duration=dur,
        stats=[
            stat("回复", t.get("replies")),
            stat("转帖", t.get("retweets")),
            stat("喜欢", t.get("likes")),
            stat("浏览", t.get("views")),
        ],
        time=fmt_time(t.get("created_timestamp")),
        quote=quote_block,
        sensitive=bool(t.get("possibly_sensitive")),
    )


async def fetch_x(client, url, service=None):
    """Only public sources: logged-in fallback could disclose protected posts."""
    tid = LINK_PATTERNS[0][1].match(url).group(1)
    try:
        return await _x_card(client, url, tid)
    except (FetchError, httpx.HTTPError, ValueError) as e:
        logger.warning(f"[LinkPreview] fxtwitter 取不到 {tid}（{e}），尝试降级")
    return await fetch_og(client, "x", url)


async def fetch_x_replies(service_url, token, tid, n=3, timeout=75, budget=25):
    """通过已登录的浏览器服务，用 conversation_id 搜索拿热门回复。

    budget 是这次愿意花的总秒数，同时决定插件等多久和服务端页面等多久，
    调小 = 出卡快但可能抓不全，调大 = 更完整但更慢。
    """
    budget = max(5, int(budget))
    ready_ms = max(4000, budget * 1000 - 2500)  # 留 2.5 秒给渲染和传输
    settle_ms = 1200 if budget >= 18 else 700
    async with httpx.AsyncClient(
        trust_env=False, timeout=timeout
    ) as c:  # 服务在 Docker 内网，不走代理
        r = await c.post(
            service_url.rstrip("/") + "/api/search",
            headers={"Authorization": "Bearer " + token},
            json={
                "query": f"conversation_id:{tid}",
                "count": max(n + 3, 6),
                "mode": "posts",
                "tab": "top",
                "ready_timeout_ms": ready_ms,
                "settle_ms": settle_ms,
            },
        )
    data = r.json() if "json" in r.headers.get("content-type", "") else {}
    if r.status_code != 200:
        raise FetchError(data.get("error") or f"浏览器服务 HTTP {r.status_code}")
    # Logged-in search finds IDs only; publish content from the public source.
    public = []
    async with make_client(timeout=8) as client:
        for item in (data.get("items") or [])[: min(n + 3, 13)]:
            ident = str(item.get("id") or "")
            if not re.fullmatch(r"\d{1,19}", ident) or ident == tid:
                continue
            try:
                post = await _x_card(client, f"https://x.com/i/status/{ident}", ident)
            except (FetchError, httpx.HTTPError, ValueError):
                continue
            if post.get("sensitive") or not post.get("text"):
                continue
            public.append(
                {
                    "author": (post.get("author") or {}).get("name"),
                    "text": flatten(post["text"]),
                    "time": post.get("time"),
                    "likes": None,
                }
            )
            if len(public) >= n:
                break
    return public


# ---------------------------------------------------------------------------
# YouTube：读视频页里的 ytInitialPlayerResponse，失败退回 oEmbed
# ---------------------------------------------------------------------------


def _json_after(page, marker):
    i = page.find(marker)
    if i < 0:
        return None
    start = page.find("{", i)
    try:
        obj, _ = json.JSONDecoder().raw_decode(page[start:])
        return obj
    except ValueError:
        return None


def _find_comment_token(obj):
    """在 ytInitialData 里找评论区的 continuation token。"""
    stack = [obj]
    while stack:
        o = stack.pop()
        if isinstance(o, dict):
            if o.get("sectionIdentifier") == "comment-item-section":
                m = re.search(r'"token":\s?"([^"]+)"', json.dumps(o))
                return m.group(1) if m else None
            stack.extend(o.values())
        elif isinstance(o, list):
            stack.extend(o)
    return None


async def _yt_comments(client, page, n):
    data = _json_after(page, "var ytInitialData") or {}
    token = _find_comment_token(data)
    key = re.search(r'"INNERTUBE_API_KEY":"([^"]+)"', page)
    ver = re.search(r'"INNERTUBE_CLIENT_VERSION":"([^"]+)"', page)
    if not (token and key and ver):
        return []
    r = await client.post(
        f"https://www.youtube.com/youtubei/v1/next?key={key.group(1)}&prettyPrint=false",
        json={
            "context": {
                "client": {
                    "clientName": "WEB",
                    "clientVersion": ver.group(1),
                    "hl": "zh-CN",
                    "gl": "US",
                }
            },
            "continuation": token,
        },
    )
    if r.status_code != 200:
        return []
    out = []
    muts = (
        (r.json().get("frameworkUpdates") or {}).get("entityBatchUpdate") or {}
    ).get("mutations") or []
    for m in muts:
        p = (m.get("payload") or {}).get("commentEntityPayload")
        if not p:
            continue
        props = p.get("properties") or {}
        out.append(
            {
                "author": (p.get("author") or {}).get("displayName"),
                "text": (props.get("content") or {}).get("content"),
                "likes": (p.get("toolbar") or {}).get("likeCountNotliked") or None,
                "time": props.get("publishedTime"),
            }
        )
        if len(out) >= n:
            break
    return out


async def fetch_youtube(client, url, comments=0):
    vid = LINK_PATTERNS[1][1].match(url).group(1)
    thumb = f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"
    try:
        page, _ = await get_html(
            client,
            f"https://www.youtube.com/watch?v={vid}&hl=zh-CN&gl=US",
            cookies={"CONSENT": "YES+cb", "SOCS": "CAI"},
        )
        pr = _json_after(page, "ytInitialPlayerResponse") or {}
        vd = pr.get("videoDetails") or {}
        mf = (pr.get("microformat") or {}).get("playerMicroformatRenderer") or {}
        if not vd.get("title"):
            raise FetchError("no videoDetails")
        thumbs = (vd.get("thumbnail") or {}).get("thumbnails") or []
        if thumbs:
            thumb = thumbs[-1].get("url", thumb)
        avatar = None
        m = re.search(r'"channelThumbnail":\{"thumbnails":\[\{"url":"([^"]+)"', page)
        if m:
            avatar = m.group(1)
        like = None
        m = re.search(r'"likeCount":"?(\d+)', page)
        if m:
            like = int(m.group(1))
        cmts = []
        if comments:
            try:
                cmts = await _yt_comments(client, page, comments)
            except (httpx.HTTPError, ValueError):
                cmts = []
        return card(
            "youtube",
            url,
            title=vd.get("title"),
            text=vd.get("shortDescription"),
            author={
                "name": vd.get("author"),
                "handle": mf.get("ownerProfileUrl", "").rsplit("/", 1)[-1] or None,
                "avatar": avatar,
            },
            images=[thumb],
            video=True,
            duration=None
            if vd.get("isLiveContent") and vd.get("isLive")
            else duration(vd.get("lengthSeconds")),
            stats=[stat("播放", vd.get("viewCount")), stat("点赞", like)],
            time=fmt_time(mf.get("publishDate")),
            note="直播中" if vd.get("isLive") else None,
            comments=cmts,
        )
    except (FetchError, httpx.HTTPError):
        r = await client.get(
            "https://www.youtube.com/oembed",
            params={"url": f"https://www.youtube.com/watch?v={vid}", "format": "json"},
        )
        if r.status_code != 200:
            raise FetchError(f"HTTP {r.status_code}")
        d = r.json()
        return card(
            "youtube",
            url,
            title=d.get("title"),
            author={"name": d.get("author_name")},
            images=[d.get("thumbnail_url") or thumb],
            video=True,
        )


# ---------------------------------------------------------------------------
# Reddit：帖子页面和 .json 接口都会拦服务器，只有 oEmbed 能用
# ---------------------------------------------------------------------------


async def fetch_reddit(client, url):
    target = url
    if "/s/" in url or "redd.it/" in url:
        # 分享短链先跟一次跳转拿到真正的帖子地址（页面本身被拦也没关系）
        try:
            r = await client.get(url)
            target = str(r.url)
        except httpx.HTTPError:
            pass
    r = await client.get("https://www.reddit.com/oembed", params={"url": target})
    if r.status_code != 200 or "json" not in r.headers.get("content-type", ""):
        raise FetchError(f"Reddit HTTP {r.status_code}")
    d = r.json()
    sub = re.search(r"/r/([A-Za-z0-9_]+)", target)
    title = d.get("title")
    if not title:
        raise FetchError("找不到帖子")
    return card(
        "reddit",
        url,
        title=title,
        author={
            "name": "u/" + d["author_name"] if d.get("author_name") else None,
            "handle": "r/" + sub.group(1) if sub else None,
        },
    )


# ---------------------------------------------------------------------------
# GitHub
# ---------------------------------------------------------------------------


async def fetch_github(client, url, token=None, comments=0):
    m = LINK_PATTERNS[3][1].match(url)
    owner, repo, kind, num = m.group(1), m.group(2), m.group(3), m.group(4)
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    async def api(path):
        r = await client.get("https://api.github.com" + path, headers=headers)
        if r.status_code != 200:
            raise FetchError(f"GitHub HTTP {r.status_code}")
        return r.json()

    if not repo:
        u = await api(f"/users/{owner}")
        return card(
            "github",
            url,
            title=u.get("name") or u.get("login"),
            text=u.get("bio"),
            author={
                "name": u.get("login"),
                "handle": u.get("company") or u.get("location"),
                "avatar": u.get("avatar_url"),
            },
            stats=[
                stat("仓库", u.get("public_repos")),
                stat("关注者", u.get("followers")),
            ],
            time=fmt_time(u.get("created_at")),
            note="用户主页",
        )
    r = await api(f"/repos/{owner}/{repo}")
    if r.get("private") is not False or r.get("visibility", "public") != "public":
        raise FetchError("仅预览公开 GitHub 仓库")
    if kind:
        it = await api(f"/repos/{owner}/{repo}/issues/{num}")
        user = it.get("user") or {}
        state = {"open": "打开", "closed": "已关闭"}.get(
            it.get("state"), it.get("state")
        )
        if it.get("pull_request") and (it["pull_request"].get("merged_at")):
            state = "已合并"
        cmts = []
        if comments and it.get("comments"):
            try:
                rows = await api(
                    f"/repos/{owner}/{repo}/issues/{num}/comments?per_page={comments}"
                )
                cmts = [
                    {
                        "author": x.get("user", {}).get("login"),
                        "text": x.get("body"),
                        "likes": compact((x.get("reactions") or {}).get("+1"))
                        if (x.get("reactions") or {}).get("+1")
                        else None,
                        "time": fmt_time(x.get("created_at")),
                    }
                    for x in rows
                ]
            except FetchError:
                cmts = []
        return card(
            "github",
            url,
            title=f"#{num} {it.get('title', '')}",
            text=it.get("body"),
            author={
                "name": user.get("login"),
                "handle": f"{owner}/{repo}",
                "avatar": user.get("avatar_url"),
            },
            stats=[["状态", state], stat("评论", it.get("comments"))],
            tags=[lb.get("name") for lb in it.get("labels") or []][:6],
            time=fmt_time(it.get("created_at")),
            comments=cmts,
            note="Pull Request" if it.get("pull_request") else "Issue",
        )
    o = r.get("owner") or {}
    return card(
        "github",
        url,
        title=r.get("full_name"),
        text=r.get("description"),
        author={"name": o.get("login"), "avatar": o.get("avatar_url")},
        images=[f"https://opengraph.githubassets.com/1/{owner}/{repo}"],
        stats=[
            stat("Star", r.get("stargazers_count")),
            stat("Fork", r.get("forks_count")),
            stat("Issue", r.get("open_issues_count")),
            ["语言", r.get("language")] if r.get("language") else None,
        ],
        tags=(r.get("topics") or [])[:6],
        time=fmt_time(r.get("pushed_at")),
        note=("已归档" if r.get("archived") else None),
    )


# ---------------------------------------------------------------------------
# Bluesky
# ---------------------------------------------------------------------------


async def fetch_bluesky(client, url, comments=0):
    m = LINK_PATTERNS[4][1].match(url)
    actor, rkey = m.group(1), m.group(2)
    base = "https://public.api.bsky.app/xrpc/"
    did = actor
    if not actor.startswith("did:"):
        r = await client.get(
            base + "com.atproto.identity.resolveHandle", params={"handle": actor}
        )
        did = r.json().get("did") if r.status_code == 200 else None
        if not did:
            raise FetchError("找不到这个账号")
    r = await client.get(
        base + "app.bsky.feed.getPostThread",
        params={
            "uri": f"at://{did}/app.bsky.feed.post/{rkey}",
            "depth": 1 if comments else 0,
        },
    )
    thread = r.json().get("thread") if r.status_code == 200 else None
    if not thread or not thread.get("post"):
        raise FetchError("找不到帖子")
    p = thread["post"]
    replies = [x.get("post") for x in thread.get("replies") or [] if x.get("post")]
    replies.sort(key=lambda x: x.get("likeCount") or 0, reverse=True)
    cmts = [
        {
            "author": (x.get("author") or {}).get("displayName")
            or (x.get("author") or {}).get("handle"),
            "text": (x.get("record") or {}).get("text"),
            "likes": compact(x.get("likeCount")) if x.get("likeCount") else None,
            "time": fmt_time((x.get("record") or {}).get("createdAt")),
        }
        for x in replies[:comments]
    ]
    a = p.get("author") or {}
    emb = p.get("embed") or {}
    imgs = [i.get("fullsize") or i.get("thumb") for i in emb.get("images") or []]
    if not imgs and (emb.get("media") or {}).get("images"):
        imgs = [i.get("fullsize") for i in emb["media"]["images"]]
    if not imgs and emb.get("thumbnail"):
        imgs = [emb["thumbnail"]]
    labels = {lb.get("val") for lb in p.get("labels") or []}
    return card(
        "bluesky",
        url,
        text=(p.get("record") or {}).get("text"),
        author={
            "name": a.get("displayName") or a.get("handle"),
            "handle": "@" + a.get("handle", ""),
            "avatar": a.get("avatar"),
        },
        images=imgs[:4],
        video="video" in (emb.get("$type") or ""),
        stats=[
            stat("回复", p.get("replyCount")),
            stat("转发", p.get("repostCount")),
            stat("喜欢", p.get("likeCount")),
        ],
        time=fmt_time((p.get("record") or {}).get("createdAt")),
        comments=cmts,
        sensitive=bool(labels & {"porn", "sexual", "nudity", "graphic-media"}),
    )


# ---------------------------------------------------------------------------
# pixiv：ajax 接口，失败退回页面元信息；R-18 作品不显示图片
# ---------------------------------------------------------------------------


async def fetch_pixiv(client, url, comments=0):
    pid = LINK_PATTERNS[5][1].match(url).group(1)
    headers = {"Referer": "https://www.pixiv.net/"}
    r = await client.get(f"https://www.pixiv.net/ajax/illust/{pid}", headers=headers)
    body = (
        r.json().get("body")
        if r.status_code == 200 and "json" in r.headers.get("content-type", "")
        else None
    )
    if not body:
        c = await fetch_og(client, "pixiv", f"https://www.pixiv.net/artworks/{pid}")
        c["images"] = []
        return c
    r18 = body.get("xRestrict", 0) > 0
    cmts = []
    if comments:
        try:
            r = await client.get(
                "https://www.pixiv.net/ajax/illusts/comments/roots",
                params={"illust_id": pid, "offset": 0, "limit": comments},
                headers=headers,
            )
            rows = (r.json().get("body") or {}).get("comments") or []
            cmts = [
                {
                    "author": x.get("userName"),
                    "text": x.get("comment") or "[贴图]",
                    "time": x.get("commentDate"),
                }
                for x in rows
            ]
        except (httpx.HTTPError, ValueError):
            cmts = []
    tags = [t.get("tag") for t in ((body.get("tags") or {}).get("tags") or [])][:6]
    img = (body.get("urls") or {}).get("regular")
    desc = re.sub(r"<br\s*/?>", "\n", body.get("description") or "")
    desc = htmllib.unescape(re.sub(r"<[^>]+>", "", desc))
    return card(
        "pixiv",
        url,
        title=body.get("title"),
        text=desc,
        author={"name": body.get("userName"), "handle": f"id {body.get('userId')}"},
        images=[] if r18 else ([img] if img else []),
        stats=[
            stat("喜欢", body.get("likeCount")),
            stat("收藏", body.get("bookmarkCount")),
            stat("浏览", body.get("viewCount")),
            stat("张数", body.get("pageCount")),
        ],
        tags=tags,
        time=fmt_time(body.get("createDate")),
        sensitive=r18,
        note="R-18 作品，不显示图片" if r18 else None,
        comments=cmts,
        referer="https://www.pixiv.net/",
    )


# ---------------------------------------------------------------------------
# Steam
# ---------------------------------------------------------------------------

BBCODE_RE = re.compile(
    r"\[/?(?:b|i|u|s|strike|h1|h2|h3|list|\*|olist|url|quote|code|spoiler|"
    r"table|tr|td|th|hr|noparse|p|img|video|previewyoutube)(?:=[^\]]*)?\]",
    re.I,
)


def _steam_plain(text):
    """评测正文里混着 BBCode 和 HTML，清干净再上卡片。"""
    t = BBCODE_RE.sub("", str(text or ""))
    t = re.sub(r"<[^>]+>", "", t)
    return re.sub(r"\s+", " ", htmllib.unescape(t)).strip()


def _steam_review_rows(page, n):
    """从社区评测页的卡片里抠出作者、推荐与否、时长、赞数和正文。"""
    rows = []
    for chunk in re.split(r'<div class="apphub_CardContentMain">', page)[1:]:
        text = re.search(
            r'<div class="date_posted">[^<]*</div>(.*?)</div>\s*</div>', chunk, re.S
        )
        body = _steam_plain(text.group(1)) if text else ""
        # 只有链接的评测没有信息量，跳过
        if not body or re.fullmatch(r"(?:https?://\S+\s*)+", body):
            continue
        title = re.search(r'<div class="title">([^<]+)</div>', chunk)
        hours = re.search(r'<div class="hours">([^<]+)</div>', chunk)
        who = re.search(
            r'<div class="apphub_CardContentAuthorName[^"]*"><a[^>]*>([^<]+)</a>', chunk
        )
        voted = re.search(r"([\d,]+)\s+people found this review helpful", chunk)
        tag = (title.group(1) if title else "").strip()
        tag = (
            "推荐"
            if tag.lower().startswith("recommended")
            else ("不推荐" if tag else "")
        )
        hrs = (
            (hours.group(1) if hours else "")
            .replace(" hrs on record", "")
            .replace(",", "")
            .strip()
        )
        try:
            hrs = str(int(float(hrs))) if hrs else ""
        except ValueError:
            hrs = ""
        if tag and hrs:
            tag += f" · {hrs} 小时"
        rows.append(
            {
                "author": (who.group(1).strip() if who else "")
                + (f"（{tag}）" if tag else ""),
                "text": body,
                "likes": voted.group(1) if voted else None,
                "time": None,
            }
        )
        if len(rows) >= n:
            break
    return rows


async def _steam_reviews(client, appid, n):
    """评测：appreviews 接口对脚本一律 302，改抓社区评测页（按最有帮助排序）。"""
    try:
        r = await client.get(
            f"https://steamcommunity.com/app/{appid}/reviews/",
            params={"browsefilter": "toprated", "snr": "1_5_100010_"},
        )
    except httpx.HTTPError:
        return []
    return _steam_review_rows(r.text, n) if r.status_code == 200 else []


async def _steam_online(client, appid, key):
    """当前在线人数，需要 Steam Web API Key。"""
    if not key:
        return None
    try:
        r = await client.get(
            "https://api.steampowered.com/ISteamUserStats/GetNumberOfCurrentPlayers/v1/",
            params={"appid": appid, "key": key},
        )
        d = r.json() if r.status_code == 200 else {}
    except (httpx.HTTPError, ValueError):
        return None
    return (d.get("response") or {}).get("player_count")


async def fetch_steam(client, url, comments=0, api_key=None):
    appid = LINK_PATTERNS[6][1].match(url).group(1)
    r = await client.get(
        "https://store.steampowered.com/api/appdetails",
        params={"appids": appid, "cc": "cn", "l": "schinese"},
    )
    d = (r.json().get(appid) or {}) if r.status_code == 200 else {}
    if not d.get("success"):
        raise FetchError("找不到这个游戏")
    g = d["data"]
    price = (
        "免费"
        if g.get("is_free")
        else ((g.get("price_overview") or {}).get("final_formatted"))
    )
    disc = (g.get("price_overview") or {}).get("discount_percent")
    if disc:
        price = f"{price}（-{disc}%）"
    rows = await _steam_reviews(client, appid, comments) if comments else []
    online = await _steam_online(client, appid, api_key)
    stats = [
        ["价格", price] if price else None,
        stat("推荐", (g.get("recommendations") or {}).get("total")),
        stat("在线", online),
        ["发售", (g.get("release_date") or {}).get("date")]
        if (g.get("release_date") or {}).get("date")
        else None,
    ]
    return card(
        "steam",
        url,
        title=g.get("name"),
        text=htmllib.unescape(re.sub(r"<[^>]+>", "", g.get("short_description") or "")),
        author={
            "name": "、".join(g.get("developers") or []) or None,
            "handle": "、".join(g.get("publishers") or []) or None,
        },
        images=[g.get("header_image")] if g.get("header_image") else [],
        stats=stats,
        tags=[x.get("description") for x in g.get("genres") or []][:6],
        comments=rows,
    )


# ---------------------------------------------------------------------------
# 维基百科
# ---------------------------------------------------------------------------


async def fetch_wikipedia(client, url):
    m = LINK_PATTERNS[7][1].match(url)
    lang, title = m.group(1).lower(), m.group(2)
    r = await client.get(
        f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/{quote(unquote(title), safe='')}",
        headers={"User-Agent": WIKI_UA},
    )
    if r.status_code != 200:
        raise FetchError(f"HTTP {r.status_code}")
    d = r.json()
    img = (d.get("originalimage") or d.get("thumbnail") or {}).get("source")
    return card(
        "wikipedia",
        url,
        title=d.get("title"),
        text=d.get("extract"),
        author={"name": f"{lang}.wikipedia.org", "handle": d.get("description")},
        images=[img] if img else [],
        time=fmt_time(d.get("timestamp")),
        note="发 /全文 可以看完整词条",
    )


# 这些章节在纯文本里基本是空的，或者只有链接列表，全文里不要
WIKI_SKIP = {
    "references",
    "external links",
    "see also",
    "further reading",
    "notes",
    "sources",
    "bibliography",
    "citations",
    "footnotes",
    "参考文献",
    "参考资料",
    "外部链接",
    "外部連結",
    "参见",
    "參見",
    "注释",
    "註釋",
    "延伸阅读",
    "延伸閱讀",
    "相关条目",
    "相關條目",
    "脚注",
    "腳注",
    "注解",
}


async def fetch_wikipedia_full(client, url):
    """维基词条全文：返回标题、首图和按章节拆好的纯文本。"""
    m = LINK_PATTERNS[7][1].match(url)
    lang, title = m.group(1).lower(), unquote(m.group(2)).replace("_", " ")
    params = {
        "action": "query",
        "prop": "extracts|pageimages",
        "explaintext": 1,
        "exsectionformat": "wiki",
        "titles": title,
        "format": "json",
        "formatversion": 2,
        "redirects": 1,
        "piprop": "thumbnail",
        "pithumbsize": 900,
    }
    if lang == "zh":
        params["variant"] = "zh-cn"  # 中文维基统一转成简体
    r = await client.get(
        f"https://{lang}.wikipedia.org/w/api.php",
        params=params,
        headers={"User-Agent": WIKI_UA},
    )
    if r.status_code != 200:
        raise FetchError(f"维基 HTTP {r.status_code}")
    pages = (r.json().get("query") or {}).get("pages") or []
    if not pages or pages[0].get("missing"):
        raise FetchError("找不到这个词条")
    pg = pages[0]
    sections, cur = [], {"title": None, "level": 1, "text": ""}
    for line in (pg.get("extract") or "").split("\n"):
        h = re.match(r"^(={2,6})\s*(.+?)\s*={2,6}$", line.strip())
        if h:
            sections.append(cur)
            cur = {"title": h.group(2), "level": len(h.group(1)), "text": ""}
        else:
            cur["text"] += line + "\n"
    sections.append(cur)
    out, skipping = [], 0
    for sec in sections:
        name = (sec["title"] or "").strip().lower()
        if skipping and sec["level"] > skipping:
            continue  # 被跳过章节的子章节也跳过
        skipping = sec["level"] if name in WIKI_SKIP else 0
        if skipping:
            continue
        sec["text"] = re.sub(r"\n{3,}", "\n\n", sec["text"]).strip()
        out.append(sec)
    # 去掉没有正文、后面也没有子章节内容的空标题
    cleaned = []
    for i, sec in enumerate(out):
        has_child = i + 1 < len(out) and out[i + 1]["level"] > sec["level"]
        if sec["text"] or has_child:
            cleaned.append(sec)
    return {
        "title": pg.get("title") or title,
        "lang": lang,
        "url": url,
        "image": (pg.get("thumbnail") or {}).get("source"),
        "sections": cleaned,
        "brand": "维基全文",
    }


# ---------------------------------------------------------------------------
# 维基文库：正文从渲染后的 HTML 转纯文本（诗词放在 poem 标签里，纯文本接口拿不到）
# ---------------------------------------------------------------------------

# 去掉页面里的导航、版权框、注释编号等非正文内容
WS_DROP = [
    "#headerContainer",
    ".ws-noexport",
    ".noprint",
    ".mw-editsection",
    "sup.reference",
    ".reference",
    "ol.references",
    ".mw-references-wrap",
    ".navbox",
    ".metadata",
    ".licenseContainer",
    "#licenseContainer",
    "style",
    "script",
    "table.ambox",
    "[role=navigation]",
    ".mw-empty-elt",
    ".wst-header",
    ".ws-header",
    ".variant-tooltip",
    "[class*=tooltip]",  # {{另}} 等模板的异文校注（鼠标悬停才显示的那部分）
]
WS_NAV_WORDS = {
    "回目录",
    "回目錄",
    "上一回",
    "下一回",
    "目录",
    "目錄",
    "返回",
    "上一卷",
    "下一卷",
    "上一章",
    "下一章",
    "←",
    "→",
}


# 只是包一层格式的模板：保留第一个参数的文字（如 {{*|并序}}、{{另|送客|送客至}}）
WS_KEEP_FIRST = {
    "*",
    "small",
    "smaller",
    "larger",
    "big",
    "另",
    "另繁",
    "yl",
    "lang",
    "!",
    "ruby",
    "nowrap",
}


def _wiki_plain(markup):
    """把头部模板参数里的维基标记去掉，只留文字。"""
    t = markup or ""
    # 从最里层开始处理模板：格式模板留第一个参数，其他模板整个去掉
    for _ in range(10):
        new = re.sub(
            r"\{\{\s*([^{}|]+?)\s*(?:\|([^{}|]*))?(?:\|[^{}]*)?\}\}",
            lambda m: (
                (m.group(2) or "")
                if m.group(1).strip().lower() in WS_KEEP_FIRST
                else ""
            ),
            t,
        )
        if new == t:
            break
        t = new
    t = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]*)\]\]", r"\1", t)
    t = re.sub(
        r"-\{(?:[^{}]*?zh-hans:([^;{}]*);[^{}]*|([^{}]*))\}-",
        lambda m: m.group(1) or m.group(2) or "",
        t,
    )
    t = re.sub(r"<[^>]+>", "", t).replace("'''", "").replace("''", "")
    return re.sub(r"\s+", " ", t).strip()


def _split_top(body, sep="|"):
    """按最外层的分隔符拆分，忽略嵌在 {{ }} 和 [[ ]] 里的。"""
    parts, cur, depth, i = [], [], 0, 0
    while i < len(body):
        two = body[i : i + 2]
        if two in ("{{", "[["):
            depth += 1
            cur.append(two)
            i += 2
            continue
        if two in ("}}", "]]"):
            depth -= 1
            cur.append(two)
            i += 2
            continue
        if body[i] == sep and depth == 0:
            parts.append("".join(cur))
            cur = []
            i += 1
            continue
        cur.append(body[i])
        i += 1
    parts.append("".join(cur))
    return parts


def _ws_header(wikitext):
    """读作品页的 {{Header}} 模板参数。模板里常常嵌套别的模板，要按括号配对找结尾。"""
    wikitext = wikitext or ""
    m = re.search(r"\{\{\s*(?:header2?|versions)\s*\|", wikitext, re.I)
    if not m:
        return {}
    depth, j = 1, m.end()
    while j < len(wikitext) and depth:
        if wikitext.startswith("{{", j):
            depth += 1
            j += 2
        elif wikitext.startswith("}}", j):
            depth -= 1
            j += 2
        else:
            j += 1
    out = {}
    for part in _split_top(wikitext[m.end() : j - 2]):
        key, eq, val = part.partition("=")
        if eq and val.strip():
            out[key.strip().lower()] = _wiki_plain(val)
    if out.get("from"):
        out["from"] = out["from"].split("#", 1)[0].strip()
    return out


def _ws_text(html):
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")  # 用内置解析器，省掉 lxml 编译依赖
    for sel in WS_DROP:
        for el in soup.select(sel):
            el.decompose()
    for br in soup.find_all("br"):
        br.replace_with("\n")
    for h in soup.find_all(["h2", "h3", "h4", "h5"]):
        marks = "=" * int(h.name[1])
        h.insert(0, f"\n{marks} ")
        h.append(f" {marks}\n")
    for el in soup.find_all(
        ["p", "div", "li", "dd", "dt", "tr", "pre", "blockquote", "center", "table"]
    ):
        el.append("\n")
    lines = []
    for line in soup.get_text().split("\n"):
        line = line.strip().replace("\u00a0", " ")
        # 章节导航行（「回目录　下一回」）不要
        if line and set(re.split(r"[\s　|·]+", line)) <= WS_NAV_WORDS:
            continue
        if line == "----":
            continue
        if line:
            lines.append(line)
    # 标题后面直到下一个同级或更高级标题都没有正文的，删掉
    head = re.compile(r"^(={2,6}) .+ \1$")
    kept = []
    for i, line in enumerate(lines):
        h = head.match(line)
        if h:
            level, empty = len(h.group(1)), True
            for nxt in lines[i + 1 :]:
                h2 = head.match(nxt)
                if h2 and len(h2.group(1)) <= level:
                    break
                if not h2:
                    empty = False
                    break
            if empty:
                continue
        kept.append(line)
    return "\n".join(kept).strip()


def _natural(t):
    return [int(x) if x.isdigit() else x for x in re.split(r"(\d+)", t)]


async def wikisource_page(client, url):
    """读取文库页面：标题、作者等头部信息、正文纯文本、子页面（章节）列表。"""
    m = next(pat for key, pat in LINK_PATTERNS if key == "wikisource").match(url)
    lang, title = m.group(1).lower(), unquote(m.group(2)).replace("_", " ")
    r = await client.get(
        f"https://{lang}.wikisource.org/w/api.php",
        headers={"User-Agent": WIKI_UA},
        params={
            "action": "parse",
            "page": title,
            "prop": "text|wikitext|links|displaytitle",
            "format": "json",
            "formatversion": 2,
            "redirects": 1,
            "disableeditsection": 1,
        },
    )
    if r.status_code != 200:
        raise FetchError(f"维基文库 HTTP {r.status_code}")
    d = r.json().get("parse")
    if not d:
        raise FetchError("找不到这个页面")
    page_title = d.get("title") or title
    hdr = _ws_header(d.get("wikitext") or "")
    if "/" in page_title and not (hdr.get("author") or hdr.get("override_author")):
        parent, _, sub = page_title.rpartition("/")
        try:
            rp = await client.get(
                f"https://{lang}.wikisource.org/w/api.php",
                headers={"User-Agent": WIKI_UA},
                params={
                    "action": "parse",
                    "page": parent,
                    "prop": "wikitext",
                    "format": "json",
                    "formatversion": 2,
                    "redirects": 1,
                },
            )
            phdr = _ws_header(((rp.json().get("parse") or {}).get("wikitext")) or "")
        except (httpx.HTTPError, ValueError):
            phdr = {}
        for k in ("author", "override_author", "times", "from"):
            if phdr.get(k) and not hdr.get(k):
                hdr[k] = phdr[k]
        if not hdr.get("title"):
            hdr["title"] = f"{phdr.get('title') or parent} · {sub}"
    prefix = page_title + "/"
    chapters = sorted(
        {
            lk["title"]
            for lk in d.get("links") or []
            if lk.get("ns") == 0
            and lk.get("exists", True)
            and lk.get("title", "").startswith(prefix)
        },
        key=_natural,
    )
    return {
        "lang": lang,
        "url": url,
        "title": hdr.get("title") or page_title,
        "author": hdr.get("override_author") or hdr.get("author"),
        "times": hdr.get("times"),
        "section": hdr.get("section"),
        "from": hdr.get("from"),
        "notes": hdr.get("notes"),
        "text": _ws_text(d.get("text") or ""),
        "chapters": [(c, c[len(prefix) :]) for c in chapters],
    }


def _ws_is_index(ws):
    """有很多章节子页面、正文又很短的，当作目录页。"""
    body = re.sub(r"^=+.*=+$", "", ws["text"], flags=re.M).strip()
    return len(ws["chapters"]) >= 3 and len(body) < 800


async def fetch_wikisource(client, url):
    ws = await wikisource_page(client, url)
    meta = " · ".join(
        x
        for x in (
            ws["times"],
            ws["section"],
            f"收录于《{ws['from']}》" if ws["from"] else None,
        )
        if x
    )
    if _ws_is_index(ws):
        names = [short for _, short in ws["chapters"]]
        text = (
            f"共 {len(names)} 章："
            + "、".join(names[:24])
            + ("……" if len(names) > 24 else "")
        )
        note = "目录页 · 发某一章的链接再用 /全文 看正文"
    else:
        text = re.sub(r"^=+\s*(.+?)\s*=+$", r"【\1】", ws["text"], flags=re.M)
        note = "发 /全文 可以看完整作品"
    return card(
        "wikisource",
        url,
        title=ws["title"],
        text=text,
        author={
            "name": ws["author"] or f"{ws['lang']}.wikisource.org",
            "handle": meta or None,
        },
        note=note,
    )


async def fetch_wikisource_full(client, url):
    """和 fetch_wikipedia_full 返回同样的结构，供 /全文 分页渲染。"""
    ws = await wikisource_page(client, url)
    if _ws_is_index(ws):
        sections = [
            {
                "title": "目录",
                "level": 2,
                "text": "\n".join(short for _, short in ws["chapters"]),
            }
        ]
        if ws["notes"]:
            sections.insert(0, {"title": None, "level": 1, "text": ws["notes"]})
    else:
        sections, cur = [], {"title": None, "level": 1, "text": ""}
        for line in ws["text"].split("\n"):
            h = re.match(r"^(={2,6})\s*(.+?)\s*={2,6}$", line.strip())
            if h:
                sections.append(cur)
                cur = {"title": h.group(2), "level": len(h.group(1)), "text": ""}
            else:
                cur["text"] += line + "\n"
        sections.append(cur)
        sections = [x for x in sections if x["text"].strip() or x["title"]]
        for x in sections:
            x["text"] = x["text"].strip()
    byline = " · ".join(x for x in (ws["author"], ws["times"], ws["section"]) if x)
    return {
        "title": ws["title"],
        "lang": ws["lang"],
        "url": url,
        "image": None,
        "byline": byline,
        "sections": sections,
        "brand": "维基文库全文",
        "icon": "文",
    }


def paginate(sections, page_chars=3500):
    """把章节按字数切成若干页；超长的章节按段落再切。每页是 [{title, level, text}]。"""
    blocks = []
    for sec in sections:
        pieces = []
        for para in (p for p in sec["text"].split("\n") if p.strip()):
            while len(para) > page_chars:  # 单段就超过一页的，硬切
                pieces.append(para[:page_chars])
                para = para[page_chars:]
            pieces.append(para)
        chunks, cur, n = [], [], 0
        for piece in pieces:
            if cur and n + len(piece) > page_chars:
                chunks.append(cur)
                cur, n = [], 0
            cur.append(piece)
            n += len(piece)
        if cur or not chunks:
            chunks.append(cur)
        for i, chunk in enumerate(chunks):
            title = (
                sec["title"] if i == 0 or not sec["title"] else sec["title"] + "（续）"
            )
            blocks.append(
                {"title": title, "level": sec["level"], "text": "\n".join(chunk)}
            )
    pages, page, size = [], [], 0
    for b in blocks:
        cost = len(b["text"]) + (40 if b["title"] else 0)
        if page and size + cost > page_chars:
            pages.append(page)
            page, size = [], 0
        page.append(b)
        size += cost
    if page:
        pages.append(page)
    return pages


# ---------------------------------------------------------------------------
# TikTok：tikwm 公共接口（官方 oEmbed 会拦服务器）
# ---------------------------------------------------------------------------


async def fetch_tiktok(client, url, comments=0):
    r = await client.post("https://www.tikwm.com/api/", data={"url": url, "hd": 0})
    d = r.json() if "json" in r.headers.get("content-type", "") else {}
    v = d.get("data") if d.get("code") == 0 else None
    if not v:
        raise FetchError(d.get("msg") or f"TikTok HTTP {r.status_code}")
    a = v.get("author") or {}
    photos = [x for x in v.get("images") or [] if isinstance(x, str)]
    cmts = []
    if comments:
        await asyncio.sleep(1.1)  # tikwm 免费接口限速 1 次/秒
        try:
            rc = await client.post(
                "https://www.tikwm.com/api/comment/list/",
                data={"url": url, "count": 30, "cursor": 0},
            )
            rows = ((rc.json().get("data") or {}).get("comments")) or []
            rows.sort(key=lambda x: x.get("digg_count") or 0, reverse=True)
            cmts = [
                {
                    "author": (x.get("user") or {}).get("nickname"),
                    "text": x.get("text"),
                    "likes": compact(x.get("digg_count"))
                    if x.get("digg_count")
                    else None,
                    "time": fmt_time(x.get("create_time")),
                }
                for x in rows[:comments]
                if x.get("text")
            ]
        except (httpx.HTTPError, ValueError):
            cmts = []
    return card(
        "tiktok",
        url,
        text=v.get("title"),
        author={
            "name": a.get("nickname"),
            "handle": "@" + a.get("unique_id", ""),
            "avatar": a.get("avatar"),
        },
        images=photos[:4] or [v.get("origin_cover") or v.get("cover")],
        video=not photos,
        duration=duration(v.get("duration")),
        stats=[
            stat("播放", v.get("play_count")),
            stat("点赞", v.get("digg_count")),
            stat("评论", v.get("comment_count")),
            stat("分享", v.get("share_count")),
            stat("收藏", v.get("collect_count")),
        ],
        time=fmt_time(v.get("create_time")),
        comments=cmts,
        note=f"图集 · {len(photos)} 张" if photos else None,
    )


# ---------------------------------------------------------------------------
# Instagram：官方接口和页面都挡服务器，借用公开的嵌入修复站读元信息
# ---------------------------------------------------------------------------

IG_MIRRORS = (
    "https://vxinstagram.com",
    "https://eeinstagram.com",
    "https://uuinstagram.com",
)


async def fetch_instagram(client, url):
    m = next(pat for key, pat in LINK_PATTERNS if key == "instagram").match(url)
    kind, code = m.group(1).lower(), m.group(2)
    path = f"/{'reel' if kind.startswith('reel') else kind}/{code}/"
    title = desc = image = None
    is_video = kind != "p"
    # 各修复站返回的内容不一样：有的只有文字和视频、有的只有封面，挨个问，凑齐为止
    for base in IG_MIRRORS:
        try:
            r = await client.get(base + path, headers={"User-Agent": EMBED_BOT_UA})
        except httpx.HTTPError:
            continue
        if r.status_code != 200 or "html" not in r.headers.get("content-type", ""):
            continue
        meta = parse_meta(r.text)
        t = meta.get("og:title") or meta.get("twitter:title") or ""
        d = meta.get("og:description") or meta.get("twitter:description")
        if t.lower() not in ("", "vxinstagram", "instafix", "instagram") and not title:
            title = t
        if d and not desc:
            desc = d
        img = meta.get("og:image") or meta.get("twitter:image")
        if img and not image and not re.search(r"\.mp4(\?|$)", img):
            image = urljoin(str(r.url), img)
        is_video = is_video or bool(meta.get("og:video"))
        if (title or desc) and image:
            break
    if not (title or desc):
        raise FetchError("Instagram 帖子读取失败（可能是私密账号或已删除）")
    # 标题形如「名字 (@用户名)」或「@用户名」
    nm = re.match(r"^(.*?)\s*\(@([^)]+)\)\s*$", title or "")
    if nm:
        author = {"name": nm.group(1) or "@" + nm.group(2), "handle": "@" + nm.group(2)}
    elif title and title.startswith("@"):
        author = {"name": title, "handle": None}
    else:
        author = {"name": title or None, "handle": None}
    return card(
        "instagram",
        url,
        text=desc,
        author=author,
        images=[image] if image else [],
        video=is_video,
        note="Reels" if kind.startswith("reel") else None,
    )


# ---------------------------------------------------------------------------
# Dailymotion / niconico


async def fetch_dailymotion(client, url):
    vid = (
        next(pat for key, pat in LINK_PATTERNS if key == "dailymotion")
        .match(url)
        .group(1)
    )
    r = await client.get(
        f"https://api.dailymotion.com/video/{vid}",
        params={
            "fields": "title,description,owner.screenname,owner.avatar_80_url,thumbnail_720_url,"
            "views_total,likes_total,duration,created_time,tags"
        },
    )
    if r.status_code != 200:
        raise FetchError(f"Dailymotion HTTP {r.status_code}")
    d = r.json()
    return card(
        "dailymotion",
        url,
        title=d.get("title"),
        text=d.get("description"),
        author={
            "name": d.get("owner.screenname"),
            "avatar": d.get("owner.avatar_80_url"),
        },
        images=[d.get("thumbnail_720_url")] if d.get("thumbnail_720_url") else [],
        video=True,
        duration=duration(d.get("duration")),
        stats=[stat("播放", d.get("views_total")), stat("点赞", d.get("likes_total"))],
        time=fmt_time(d.get("created_time")),
        tags=(d.get("tags") or [])[:6],
    )


async def fetch_niconico(client, url):
    vid = (
        next(pat for key, pat in LINK_PATTERNS if key == "niconico").match(url).group(1)
    )
    r = await client.get(f"https://ext.nicovideo.jp/api/getthumbinfo/{vid}")
    x = r.text
    if r.status_code != 200 or 'status="ok"' not in x:
        raise FetchError("找不到这个视频")

    def tag(name):
        m = re.search(rf"<{name}>(.*?)</{name}>", x, re.S)
        return htmllib.unescape(m.group(1)).strip() if m else None

    length = tag("length") or ""
    secs = (
        sum(
            int(p) * 60**i
            for i, p in enumerate(reversed(length.split(":")))
            if p.isdigit()
        )
        if length
        else None
    )
    thumb = tag("thumbnail_url")
    # 新视频有 .L 大图，老视频没有，挨个试
    if thumb:
        for cand in (thumb + ".L", thumb + ".M", thumb):
            try:
                if (await client.head(cand)).status_code == 200:
                    thumb = cand
                    break
            except httpx.HTTPError:
                pass
    return card(
        "niconico",
        url,
        title=tag("title"),
        text=tag("description"),
        author={
            "name": tag("user_nickname") or tag("ch_name"),
            "avatar": tag("user_icon_url") or tag("ch_icon_url"),
        },
        images=[thumb] if thumb else [],
        video=True,
        duration=duration(secs),
        stats=[
            stat("播放", tag("view_counter")),
            stat("评论", tag("comment_num")),
            stat("收藏", tag("mylist_counter")),
        ],
        time=fmt_time(tag("first_retrieve")),
        tags=re.findall(r"<tag[^>]*>(.*?)</tag>", x)[:6],
    )


# ---------------------------------------------------------------------------
# oEmbed 类：Spotify / Vimeo / SoundCloud
# ---------------------------------------------------------------------------

OEMBED = {
    "spotify": "https://open.spotify.com/oembed",
    "vimeo": "https://vimeo.com/api/oembed.json",
    "soundcloud": "https://soundcloud.com/oembed",
}


async def fetch_oembed(client, platform, url):
    r = await client.get(OEMBED[platform], params={"url": url, "format": "json"})
    if r.status_code != 200 or "json" not in r.headers.get("content-type", ""):
        return await fetch_og(client, platform, url)
    d = r.json()
    return card(
        platform,
        url,
        title=d.get("title"),
        text=d.get("description"),
        author={"name": d.get("author_name"), "handle": None},
        images=[d.get("thumbnail_url")] if d.get("thumbnail_url") else [],
        video=platform in ("tiktok", "vimeo"),
        duration=duration(d.get("duration")),
    )


# 能拿到评论的平台（X、Reddit 不登录拿不到；Steam 评测接口会拦服务器）
COMMENT_PLATFORMS = {"youtube", "github", "bluesky", "pixiv", "tiktok", "x", "steam"}


TWITCH_CLIENT_ID = "kimne78kx3ncx6brgo4mv6wki5h1ko"  # 网页版公开 Client-ID，无需登录
TWITCH_RESERVED = {
    "directory",
    "videos",
    "settings",
    "search",
    "p",
    "downloads",
    "subscriptions",
    "wallet",
    "drops",
    "inventory",
    "jobs",
    "turbo",
    "creatorcamp",
    "store",
    "friends",
}
TWITCH_USER_Q = """
query($login:String!){
  user(login:$login){
    displayName description profileImageURL(width:600) bannerImageURL
    stream{ id title viewersCount createdAt
      game{ displayName }
      previewImageURL(width:1280,height:720)
    }
  }
}"""
TWITCH_CLIP_Q = """
query($slug:ID!){
  clip(slug:$slug){
    title durationSeconds viewCount createdAt thumbnailURL(width:1280,height:720)
    broadcaster{ displayName login }
    curator{ displayName }
    game{ displayName }
  }
}"""


async def _twitch_gql(client, query, variables):
    r = await client.post(
        "https://gql.twitch.tv/gql",
        headers={"Client-ID": TWITCH_CLIENT_ID},
        json={"query": query, "variables": variables},
    )
    if r.status_code != 200:
        raise FetchError(f"Twitch HTTP {r.status_code}")
    return r.json().get("data") or {}


def twitch_target(url):
    """解析 Twitch 链接，返回 ("clip", slug) / ("channel", login) / ("og", None)。"""
    u = urlsplit(url)
    parts = [x for x in u.path.split("/") if x]
    if (u.hostname or "").endswith("clips.twitch.tv") and parts:
        return "clip", parts[0]
    if len(parts) >= 3 and parts[1] == "clip":
        return "clip", parts[2]
    if parts[:1] == ["videos"]:
        return "og", None
    login = next((x for x in parts if x.lower() not in TWITCH_RESERVED), "")
    return ("channel", login) if login else ("og", None)


async def fetch_twitch(client, url):
    """Twitch 频道和切片。

    网页对爬虫会返回登录墙（卡片只剩「登录 Twitch」），所以走网页版公开 GQL：
    频道资料、是否在播、观众数、分类、16:9 预览图都能拿到。
    """
    kind, value = twitch_target(url)
    clip_slug = value if kind == "clip" else None

    if clip_slug:
        data = await _twitch_gql(client, TWITCH_CLIP_Q, {"slug": clip_slug})
        clip = data.get("clip")
        if not clip:
            raise FetchError("这个切片不存在或已删除")
        b = clip.get("broadcaster") or {}
        cur = clip.get("curator") or {}
        return {
            "platform": "twitch",
            "platform_name": "Twitch",
            "color": PLATFORMS["twitch"][1],
            "url": url,
            "title": clip.get("title") or "Twitch 切片",
            "text": None,
            "author": {
                "name": b.get("displayName") or b.get("login"),
                "handle": ("@" + b["login"]) if b.get("login") else None,
                "avatar": None,
                "bio": None,
            },
            "images": [clip["thumbnailURL"]] if clip.get("thumbnailURL") else [],
            "stats": [
                s
                for s in (
                    ["播放", compact(clip.get("viewCount"))],
                    ["时长", duration(clip.get("durationSeconds"))],
                    ["分类", (clip.get("game") or {}).get("displayName")],
                    ["剪辑", cur.get("displayName")],
                )
                if s[1]
            ],
            "tags": [],
            "time": fmt_time(clip.get("createdAt")),
            "comments": [],
            "quote": None,
            "video": True,
            "duration": duration(clip.get("durationSeconds")),
            "sensitive": False,
            "note": "切片",
            "comments_mode": False,
            "blur": False,
            "domain": "clips.twitch.tv",
            "short_url": "clips.twitch.tv/" + clip_slug,
            "no_comments_reason": None,
        }

    if kind == "og":
        return await fetch_og(client, "twitch", url)
    login = value
    data = await _twitch_gql(client, TWITCH_USER_Q, {"login": login})
    user = data.get("user")
    if not user:
        raise FetchError("这个 Twitch 频道不存在")

    stream = user.get("stream")
    name = user.get("displayName") or login
    game = (stream or {}).get("game") or {}
    if stream:
        preview = (
            stream.get("previewImageURL")
            or f"https://static-cdn.jtvnw.net/previews-ttv/live_user_{login}-1280x720.jpg"
        )
        title, note = stream.get("title") or f"{name} 正在直播", None
        stats = [
            s
            for s in (
                ["观看", compact(stream.get("viewersCount"))],
                ["分类", game.get("displayName")],
            )
            if s[1]
        ]
        time_text = fmt_time(stream.get("createdAt"))
        tags = [t for t in (game.get("displayName"), "直播中") if t]
    else:
        preview = None
        title, note = f"{name} 的频道", "当前未开播"
        stats, time_text, tags = [], None, []

    return {
        "platform": "twitch",
        "platform_name": "Twitch",
        "color": PLATFORMS["twitch"][1],
        "url": url,
        "title": title,
        "text": user.get("description"),
        "author": {
            "name": name,
            "handle": "@" + login,
            "avatar": user.get("profileImageURL"),
            "bio": None,
        },
        "images": [preview] if preview else [],
        "stats": stats,
        "tags": tags,
        "time": time_text,
        "comments": [],
        "quote": None,
        "video": bool(stream),
        "duration": None,
        "sensitive": False,
        "note": note,
        "comments_mode": False,
        "blur": False,
        "domain": "twitch.tv",
        "short_url": "twitch.tv/" + login,
        "no_comments_reason": None,
    }


async def fetch(
    client,
    platform,
    url,
    github_token=None,
    comments=0,
    steam_api_key=None,
    x_service=None,
):
    if platform in DOMESTIC_HOSTS:
        return await fetch_domestic(client, platform, url)
    if platform == "x":
        return await fetch_x(client, url, x_service)
    if platform == "youtube":
        return await fetch_youtube(client, url, comments)
    if platform == "reddit":
        return await fetch_reddit(client, url)
    if platform == "github":
        return await fetch_github(client, url, github_token, comments)
    if platform == "bluesky":
        return await fetch_bluesky(client, url, comments)
    if platform == "pixiv":
        return await fetch_pixiv(client, url, comments)
    if platform == "steam":
        return await fetch_steam(client, url, comments, steam_api_key)
    if platform == "wikipedia":
        return await fetch_wikipedia(client, url)
    if platform == "wikisource":
        return await fetch_wikisource(client, url)
    if platform == "tiktok":
        return await fetch_tiktok(client, url, comments)
    if platform == "instagram":
        return await fetch_instagram(client, url)
    if platform == "dailymotion":
        return await fetch_dailymotion(client, url)
    if platform == "niconico":
        return await fetch_niconico(client, url)
    if platform == "twitch":
        return await fetch_twitch(client, url)
    if platform in OEMBED:
        return await fetch_oembed(client, platform, url)
    return await fetch_og(client, platform, url)


def make_client(proxy=None, timeout=12):
    return PreviewClient(
        headers={"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8"},
        follow_redirects=True,
        max_redirects=5,
        timeout=timeout,
        transport=PublicTransport(proxy=proxy or None),
        trust_env=False,
    )


async def fetch_domestic(client, platform, url):
    """Read public share pages; never execute embedded scripts or bypass login walls."""
    for _ in range(6):
        parsed = urlsplit(url)
        if (
            parsed.scheme not in ("http", "https")
            or parsed.hostname not in DOMESTIC_HOSTS[platform]
            or parsed.username
            or parsed.password
        ):
            raise FetchError("分享链接跳转到了不支持的域名")
        if platform == "bilibili":
            match = re.fullmatch(
                r"/video/(BV[0-9A-Za-z]{10}|av\d+)/?", parsed.path, re.I
            )
            if match and parsed.hostname != "b23.tv":
                ident = match.group(1)
                params = (
                    {"aid": ident[2:]}
                    if ident.lower().startswith("av")
                    else {"bvid": "BV" + ident[2:]}
                )
                response = await client.get(
                    "https://api.bilibili.com/x/web-interface/view",
                    params=params,
                    headers={"Referer": "https://www.bilibili.com/"},
                )
                response.raise_for_status()
                payload = response.json()
                if payload.get("code") != 0 or not isinstance(
                    payload.get("data"), dict
                ):
                    raise FetchError("B站视频不存在或暂时无法访问")
                data = payload["data"]
                owner, stats = data.get("owner") or {}, data.get("stat") or {}
                return card(
                    platform,
                    url,
                    title=data.get("title"),
                    text=data.get("desc"),
                    author={"name": owner.get("name"), "avatar": owner.get("face")},
                    images=[data["pic"]] if data.get("pic") else [],
                    video=True,
                    duration=duration(data.get("duration")),
                    time=fmt_time(data.get("pubdate")),
                    stats=[
                        stat(label, stats.get(key))
                        for label, key in (
                            ("播放", "view"),
                            ("点赞", "like"),
                            ("投币", "coin"),
                            ("收藏", "favorite"),
                        )
                    ],
                    referer="https://www.bilibili.com/",
                )
        response = await client.get(url, follow_redirects=False)
        if response.is_redirect:
            location = response.headers.get("location")
            if not location:
                raise FetchError("分享链接没有跳转目标")
            url = urljoin(url, location)
            continue
        response.raise_for_status()
        meta = parse_meta(response.text)
        title = meta.get("og:title") or meta.get("twitter:title") or meta.get("title")
        desc = (
            meta.get("og:description")
            or meta.get("description")
            or meta.get("twitter:description")
        )
        if not title or any(
            word in title.lower()
            for word in (
                "登录",
                "安全验证",
                "验证码",
                "security verification",
                "passport",
                "access denied",
            )
        ):
            raise FetchError("平台要求登录或验证，暂时无法获取公开预览")
        if title.strip() in (
            PLATFORMS[platform][0],
            "小红书 - 你的生活指南",
            "知乎 - 有问题，就会有答案",
            "抖音-记录美好生活",
        ):
            raise FetchError("平台未返回这条内容的公开预览")
        if desc and title and re.sub(r"\s+", "", desc) == re.sub(r"\s+", "", title):
            desc = None
        image = meta.get("og:image") or meta.get("twitter:image")
        return card(
            platform,
            url,
            title=title,
            text=desc,
            author={"name": meta["author"]} if meta.get("author") else None,
            images=[urljoin(url, image)] if image else [],
            video=(meta.get("og:type") or "").startswith("video"),
            note="公开分享页预览",
            referer=url,
        )
    raise FetchError("分享链接跳转次数过多")
