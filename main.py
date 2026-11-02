"""外链预览：识别群聊里的国外平台链接，抓取内容画成卡片图片发回群里。"""

import asyncio
import hashlib
import json
import re
import shutil
import time
from pathlib import Path

import httpx
from urllib.parse import urlsplit

import astrbot.api.message_components as Comp
from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, MessageChain, filter
from astrbot.api.star import Context, Star, StarTools

from . import fetchers, render, wordfilter

HELP = """外链解析 Ex
群里发 B站 / 抖音 / 小红书 / 微博 / 知乎 / YouTube / TikTok / Instagram / X / GitHub / Reddit / Bluesky / pixiv / Steam / 维基百科 / 维基文库 / Dailymotion / niconico / Spotify 等链接，会自动回一张预览卡片（带几条热门评论）。
/预览 链接：手动预览任意网页链接（也可用 /preview）
/评论 [链接]：单独看一条链接的评论，最多 10 条；不带链接时用本群最近预览过的那条（也可用 /comments）
/翻译 [链接]：出一张带译文的卡片（外语帖子自动预览时已带译文，不用再发这条）
/全文 [维基链接]：把维基百科词条或维基文库作品的全文分页，合并转发发出（也可用 /维基全文）
/预览图片 [开/关/默认]：管理员切换本群卡片是否显示配图和封面，不带参数查看当前状态
/预览帮助：查看这条帮助
能拿到评论的平台：YouTube、TikTok、X（需配置浏览器服务，较慢）、GitHub Issue/PR、Bluesky、pixiv。Instagram、Reddit 拿不到评论。"""

PLUGIN_NAME = "astrbot_plugin_link_ex"
# 本插件注册的指令和别名，用来把「指令消息」和「普通聊天」区分开
COMMAND_NAMES = {
    "预览", "preview", "评论", "comments", "看评论",
    "全文", "fulltext", "维基全文", "预览图片", "previewimg", "预览配图",
    "预览帮助", "previewhelp", "翻译", "translate", "翻译帖子",
}
# 词表默认放在插件数据目录（data/plugin_data/<插件名>/）下，随插件数据一起迁移和审计。
WORDS_NAME = "political.txt"
RESTRICTED_NAME = "restricted.txt"
# 旧版本把词表写在 data/sensitive_words/，只在迁移时读取一次，不再往那里写。
LEGACY_WORDS_FILE = "data/sensitive_words/political.txt"
BLOCK_NOTICE = "这个链接的内容包含屏蔽词，不予预览。"
SEND_FAIL_NOTICE = "这张预览卡片发送失败（可能被 QQ 拦截了），请直接点链接查看。"
REPLY_BLOCK_NOTICE = "（这条回复包含屏蔽词，已拦截）"


def _cookie_pair(raw):
    """从粘贴的 Cookie 里抠出 auth_token 和 ct0，认不出就返回 None。"""
    text = str(raw or "").strip()
    if not text:
        return None
    auth = re.search(r"auth_token\s*[=:]\s*([0-9a-zA-Z]{20,})", text)
    ct0 = re.search(r"ct0\s*[=:]\s*([0-9a-zA-Z]{20,})", text)
    if auth and ct0:
        return auth.group(1), ct0.group(1)
    # 允许只粘两条值，按「长的当 ct0」兜底
    parts = [x for x in re.split(r"[;\s]+", text) if re.fullmatch(r"[0-9a-zA-Z]{20,}", x)]
    if len(parts) == 2:
        parts.sort(key=len)
        return parts[0], parts[1]
    return None


class Blocked(Exception):
    """内容命中敏感词。"""
    notice = None


class RestrictedBlocked(Blocked):
    """内容被判定为不适宜（命中分级词表，或被平台标记）。"""
    notice = "这个链接可能含成人内容，不予预览。"


def _bool(v, default=False):
    if isinstance(v, bool):
        return v
    if v is None:
        return default
    return str(v).strip().lower() in ("1", "true", "yes", "on", "开", "开启")


def _int(v, default, lo, hi):
    try:
        return max(lo, min(hi, int(v)))
    except (TypeError, ValueError):
        return default


class LinkPreviewPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self.data_dir = Path(StarTools.get_data_dir(PLUGIN_NAME))
        self.cache_dir = self.data_dir / "cards"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        # 每个群单独的「显示配图」开关：会话 -> True/False，没设置的跟随全局配置
        self._img_file = self.data_dir / "image_switch.json"
        try:
            self._img_switch = json.loads(self._img_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self._img_switch = {}
        self._recent = {}      # (会话, 链接) -> 上次预览时间，用来去重
        self._last_link = {}   # 会话 -> 最近一次预览的 (平台, 链接)，给 /评论 用
        self._x_replies = {}   # 帖子 ID -> (时间, 回复列表)；后台没等完的结果留给 /评论 用
        words_file = self._words_path("block_words_file", WORDS_NAME, LEGACY_WORDS_FILE)
        try:
            self.filter = wordfilter.WordFilter(words_file, self.config.get("block_words") or [])
            logger.info(f"[LinkPreview] 敏感词表已加载 {self.filter.count} 个词：{words_file}")
        except OSError as e:
            logger.error(f"[LinkPreview] 敏感词表加载失败：{e}")
            self.filter = wordfilter.WordFilter(None, self.config.get("block_words") or [])
        restricted_file = self._words_path("restricted_words_file", RESTRICTED_NAME, None)
        try:
            self.restricted = wordfilter.WordFilter(restricted_file, self.config.get("restricted_words") or [], wordfilter.BUNDLED_RESTRICTED)
            logger.info(f"[LinkPreview] 分级词表已加载 {self.restricted.count} 个词：{restricted_file}")
        except OSError as e:
            logger.error(f"[LinkPreview] 分级词表加载失败：{e}")
            self.restricted = wordfilter.WordFilter(None, self.config.get("restricted_words") or [], wordfilter.BUNDLED_RESTRICTED)

    async def initialize(self):
        """插件被激活时调用；这里才保证有事件循环，用来写入手填的 Cookie。"""
        if _cookie_pair(self.config.get("x_cookie", "")):
            await self._push_cookie()
        # 填了 Cookie 却没配服务地址，评论永远出不来，给一句明确的提示（卡片本身不受影响）
        service, token = self._x_service()
        if _cookie_pair(self.config.get("x_cookie", "")) and not (service and token):
            logger.warning(
                "[LinkPreview] 填了 x_cookie 但没配 x_browser_url / x_browser_token，"
                "X 热门评论不会显示；卡片正文和配图不受影响。部署方法见 README 的「X 评论」一节"
            )

    async def terminate(self):
        pass

    def _words_path(self, key, name, legacy):
        """词表路径：配置留空就用插件数据目录下的文件。

        旧版本把词表写在 data/sensitive_words/ 里，第一次升级时把旧文件复制过来，
        之后只读写插件数据目录，不再碰旧位置（旧文件保留，避免影响别的插件）。
        """
        raw = str(self.config.get(key, "") or "").strip()
        if raw:
            return raw
        path = self.data_dir / name
        old = Path(legacy) if legacy else None
        if old is not None and not path.exists() and old.exists():
            try:
                shutil.copyfile(old, path)
                logger.info(f"[LinkPreview] 已把旧词表 {old} 迁移到 {path}")
            except OSError as e:
                logger.warning(f"[LinkPreview] 迁移旧词表失败：{e}")
        return str(path)

    # ------------------------------------------------------------------ 配置

    def _platforms(self):
        conf = self.config.get("platforms") or {}
        return {k: _bool(conf.get(k), True) for k in fetchers.PLATFORMS if k != "web"}

    def _allowed(self, event):
        if not _bool(self.config.get("enabled", True), True):
            return False
        gid = str(event.get_group_id() or "")
        if not gid:
            return _bool(self.config.get("private_enabled", False))
        white = [str(x).strip() for x in self.config.get("group_whitelist") or [] if str(x).strip()]
        black = [str(x).strip() for x in self.config.get("group_blacklist") or [] if str(x).strip()]
        if white and gid not in white:
            return False
        return gid not in black

    # ------------------------------------------------------------------ 敏感词

    def _block_on(self):
        return _bool(self.config.get("block_enabled", True), True)

    def _mask_mode(self):
        return self.config.get("block_mode", "整条不发") == "打码后发送"

    def _filter_card(self, card):
        """评论命中的单独去掉；正文命中按设置整条不发或打码。分级内容一律整条不发。"""
        if _bool(self.config.get("restricted_enabled", True), True):
            card["comments"] = [c for c in card.get("comments") or [] if not self.restricted.find(c.get("author"), c.get("text"))]
            a, q = card.get("author") or {}, card.get("quote") or {}
            flagged = card.get("sensitive") and _bool(self.config.get("restricted_block_flagged", True), True)
            if flagged or self.restricted.find(card.get("title"), card.get("text"), a.get("name"), a.get("handle"),
                                        a.get("bio"), q.get("text"), " ".join(card.get("tags") or [])):
                raise RestrictedBlocked()
        if not self._block_on():
            return card
        f = self.filter
        card["comments"] = [c for c in card.get("comments") or [] if not f.find(c.get("author"), c.get("text"))]
        author = card.get("author") or {}
        quote = card.get("quote") or {}

        def fields():
            a, q = card.get("author") or {}, card.get("quote") or {}
            return (card.get("title"), card.get("text"), a.get("name"), a.get("handle"),
                    q.get("author"), q.get("text"), " ".join(card.get("tags") or []), card.get("note"))

        # 按账号屏蔽：作者简介里带敏感词的账号，不管这条发的是什么都不预览
        if f.find(author.get("bio")):
            raise Blocked()
        if not f.find(*fields()):
            return card
        if not self._mask_mode():
            raise Blocked()
        card["title"], card["text"] = f.mask(card.get("title")), f.mask(card.get("text"))
        if author:
            card["author"] = dict(author, name=f.mask(author.get("name")), handle=f.mask(author.get("handle")))
        if quote:
            card["quote"] = dict(quote, author=f.mask(quote.get("author")), text=f.mask(quote.get("text")))
        card["tags"] = [f.mask(t) for t in card.get("tags") or []]
        card["images"] = []      # 文字打码了，配图里同样的内容遮不住，干脆不放
        card["note"] = "含屏蔽词，已打码"
        card["sensitive"] = True
        if f.find(*fields()):    # 插字写法打不了码，只能整条不发
            raise Blocked()
        return card

    def _filter_article(self, article):
        texts = [article.get("title"), article.get("byline")]
        for s in article["sections"]:
            texts += [s.get("title"), s.get("text")]
        # 分级内容一律整条不发，不打码（和卡片走同一套判定）
        if _bool(self.config.get("restricted_enabled", True), True) and self.restricted.find(*texts):
            raise RestrictedBlocked()
        if not self._block_on():
            return article
        f = self.filter
        if not f.find(*texts):
            return article
        if not self._mask_mode():
            raise Blocked()
        article = dict(article, title=f.mask(article.get("title")), byline=f.mask(article.get("byline")))
        article["sections"] = [dict(s, title=f.mask(s.get("title")), text=f.mask(s.get("text"))) for s in article["sections"]]
        texts = [article["title"], article["byline"]] + [x for s in article["sections"] for x in (s["title"], s["text"])]
        if f.find(*texts):
            raise Blocked()
        return article

    # ------------------------------------------------------------------ X 回复

    def _x_service(self):
        """浏览器服务地址和 Token，只认本插件的配置。"""
        url = str(self.config.get("x_browser_url", "") or "").strip()
        token = str(self.config.get("x_browser_token", "") or "").strip()
        return (url, token) if url and len(token) >= 32 else (None, None)

    async def _push_cookie(self):
        """把配置里手填的 Cookie 写进抓取服务，登录方式之外的另一条路。"""
        pair = _cookie_pair(self.config.get("x_cookie", ""))
        if not pair:
            return
        url, token = self._x_service()
        if not url or not token:
            logger.warning("[LinkPreview] 填了 x_cookie 但没配 x_browser_url/token，跳过")
            return
        try:
            async with httpx.AsyncClient(trust_env=False, timeout=20) as c:
                r = await c.post(url.rstrip("/") + "/api/cookies",
                                 headers={"Authorization": "Bearer " + token},
                                 json={"auth_token": pair[0], "ct0": pair[1]})
            if r.status_code == 200:
                logger.info("[LinkPreview] 已写入手填的 X Cookie")
            else:
                logger.warning(f"[LinkPreview] 写入 X Cookie 失败：HTTP {r.status_code}")
        except Exception as e:
            logger.warning(f"[LinkPreview] 写入 X Cookie 出错：{e}")

    async def _x_replies_for(self, url, n, wait):
        """等最多 wait 秒；没等完就先返回空，后台继续抓，结果缓存给下次（比如 /评论）用。"""
        m = re.search(r"/status(?:es)?/(\d{1,19})", url)
        service, token = self._x_service()
        if not m or not service or not _bool(self.config.get("x_comments", True), True):
            return []
        tid = m.group(1)
        hit = self._x_replies.get(tid)
        if hit and time.time() - hit[0] < 600:
            return hit[1][:n]

        async def job():
            try:
                rows = await fetchers.fetch_x_replies(service, token, tid, max(n, 10), budget=wait)
            except Exception as e:
                logger.info(f"[LinkPreview] X 回复获取失败 {tid}：{e}")
                return []
            self._x_replies[tid] = (time.time(), rows)
            logger.info(f"[LinkPreview] X 回复 {tid} 抓到 {len(rows)} 条")
            return rows

        task = asyncio.ensure_future(job())
        try:
            rows = await asyncio.wait_for(asyncio.shield(task), wait)
        except asyncio.TimeoutError:
            logger.warning(f"[LinkPreview] X 回复 {wait} 秒内没抓完，先发不带评论的卡片（后台会继续抓，稍后 /评论 能看）")
            return []
        return rows[:n]

    # ------------------------------------------------------------------ 发送

    async def _send_or_notice(self, event, chain):
        """自己发，发不出去（比如被 QQ 拦截）就返回 False，由调用方补一句提醒。"""
        try:
            await event.send(MessageChain(chain))
            return True
        except Exception as e:
            logger.warning(f"[LinkPreview] 发送失败：{e}")
            return False

    # ------------------------------------------------------------------ 工具

    @staticmethod
    def _message_text(event):
        """消息文字 + QQ 分享卡片（Json 消息）里的链接。"""
        parts = [event.message_str or ""]
        for seg in event.get_messages() or []:
            if isinstance(seg, Comp.Json):
                data = seg.data if isinstance(seg.data, str) else json.dumps(seg.data, ensure_ascii=False)
                parts.append(data.replace("\\/", "/"))
        return "\n".join(parts)

    @staticmethod
    def _is_command(text):
        """判断这条消息是不是本插件的指令。

        AstrBot 交给插件前可能已经把命令前缀剥掉了，只判断开头的 "/" 不够，
        否则 /翻译 <链接> 会同时触发自动预览，出一张卡又发一条译文。
        """
        t = str(text or "").strip()
        if not t:
            return False
        if t[0] in "/!！／！":
            return True
        return t.split()[0] in COMMAND_NAMES

    def _duplicate(self, session, url):
        window = _int(self.config.get("dedupe_seconds", 30), 30, 0, 86400)
        now = time.time()
        # 顺手清掉过期记录
        for k, t in list(self._recent.items()):
            if now - t > max(window, 60):
                self._recent.pop(k, None)
        key = (session, fetchers.canonical_url(url))
        if window and now - self._recent.get(key, 0) < window:
            return True
        self._recent[key] = now
        return False

    def _clean_cache(self):
        cutoff = time.time() - 6 * 3600
        for f in self.cache_dir.glob("*.jpg"):
            try:
                if f.stat().st_mtime < cutoff:
                    f.unlink()
            except OSError:
                pass

    def _show_images(self, session):
        if session in self._img_switch:
            return bool(self._img_switch[session])
        return _bool(self.config.get("show_images", True), True)

    async def _translate_text(self, text, umo=None, timeout=45):
        """调 AstrBot 当前使用的对话模型翻译。没配模型就抛错。"""
        try:
            provider = self.context.get_using_provider(umo)
        except ValueError as e:      # 该会话配的不是对话模型（比如选成了 TTS）
            raise RuntimeError(f"当前会话的模型不能用来翻译：{e}") from e
        if not provider:
            raise RuntimeError("没有可用的对话模型，请先在 AstrBot 里配置 LLM 提供商")
        target = str(self.config.get("translate_target", "简体中文") or "简体中文").strip()
        resp = await asyncio.wait_for(
            provider.text_chat(
                prompt=text,
                system_prompt=(f"把用户给的内容翻译成{target}。只输出译文，保留原有换行和分段，"
                               "不要解释、不要加引号、不要重复原文。"),
                contexts=[],
            ),
            timeout,
        )
        out = (getattr(resp, "completion_text", "") or "").strip()
        if not out:
            raise RuntimeError("模型没有返回内容")
        return out

    async def _translate_card(self, card, umo=None):
        """翻译标题和正文，拼成一段放卡片里。"""
        parts = [x.strip() for x in (card.get("title"), card.get("text")) if (x or "").strip()]
        if not parts:
            return None
        return await self._translate_text("\n\n".join(parts), umo)

    async def _t2i(self, tmpl_path, data, out, attempts=3):
        """用 AstrBot 的文转图服务出图，失败重试，再裁掉多余留白。

        远端服务偶尔 503，重试一两次基本能过；裁边是因为它的视口高度固定 720，
        矮卡片下方会留一大片纯背景色。
        """
        tmpl = tmpl_path.read_text(encoding="utf-8")
        timeout = _int(self.config.get("render_timeout", 25), 25, 5, 120)
        last = None
        for i in range(attempts):
            try:
                path = await asyncio.wait_for(
                    self.html_render(tmpl, data, return_url=False, options=render.t2i_options()),
                    timeout,
                )
                shutil.copyfile(path, out)
                render.crop_image(str(out))
                return str(out)
            except Exception as e:
                last = e
                logger.warning(f"[LinkPreview] 文转图失败（第 {i + 1}/{attempts} 次）：{e}")
                if i + 1 < attempts:
                    await asyncio.sleep(1.2 * (i + 1))
        raise RuntimeError(f"文转图服务不可用：{last}")

    async def _render_html(self, tmpl_path, card, out):
        theme = "light" if self.config.get("theme") == "light" else "dark"
        return await self._t2i(tmpl_path, {"c": card, "theme": theme, "t2i": True}, out)

    async def _render_page(self, article, blocks, no, total, hidden, theme, out):
        data = {"a": article, "blocks": blocks, "no": no, "total": total, "hidden": hidden,
                "theme": "light" if theme == "light" else "dark", "t2i": True}
        return await self._t2i(render.ARTICLE, data, out)

    async def _make_card_image(self, platform, url, comments_mode=False, session=None, translate=False):
        """抓取 + 渲染，返回图片路径；失败返回 None。"""
        n_comments = 10 if comments_mode else _int(self.config.get("comment_count", 3), 3, 0, 10)
        timeout = _int(self.config.get("fetch_timeout", 12), 12, 3, 60)
        async with fetchers.make_client(self.config.get("proxy") or None, timeout) as client:
            x_task = None
            if platform == "x" and n_comments:
                wait = 75 if comments_mode else _int(self.config.get("x_comments_wait", 25), 25, 0, 60)
                x_task = asyncio.ensure_future(self._x_replies_for(url, n_comments, wait))
            card = await fetchers.fetch(client, platform, url,
                                        github_token=self.config.get("github_token") or None,
                                        comments=n_comments,
                                        steam_api_key=self.config.get("steam_api_key") or None,
                                        x_service=self._x_service() if platform == "x" else None)
            if x_task:
                card["comments"] = await x_task
            card = self._filter_card(card)
            auto = _bool(self.config.get("translate_auto", True), True)
            if translate or (auto and fetchers.needs_translation(card.get("text") or card.get("title"))):
                try:
                    card["translation"] = await self._translate_card(card, session)
                    logger.info("[LinkPreview] 已翻译卡片正文")
                except Exception as e:  # noqa: BLE001 - 翻译失败不该影响出图
                    logger.warning(f"[LinkPreview] 翻译失败：{e}")
                    if translate:
                        raise RuntimeError(f"翻译失败：{e}") from e
            if comments_mode and not card.get("comments"):
                card["no_comments_reason"] = (
                    "这个平台拿不到评论" if platform not in fetchers.COMMENT_PLATFORMS else "暂时没有评论"
                )
            card = await render.prepare(
                client, card,
                text_length=_int(self.config.get("text_length", 420), 420, 60, 2000),
                show_images=self._show_images(session),
                comments_mode=comments_mode,
            )
        if card.get("sensitive") and not _bool(self.config.get("blur_sensitive", True), True):
            card["blur"] = False
        name = hashlib.md5(f"{url}|{comments_mode}|{time.time()}".encode()).hexdigest()[:16] + ".jpg"
        out = self.cache_dir / name
        return await self._render_html(render.TEMPLATE, card, out)

    async def _preview(self, event, links, comments_mode=False, quiet=True, translate=False):
        self._clean_cache()
        session = event.unified_msg_origin
        for platform, url in links:
            logger.info(f"[LinkPreview] 开始预览 {platform} {url}")
            try:
                path = await self._make_card_image(platform, url, comments_mode, session, translate)
            except Blocked as e:
                logger.info(f"[LinkPreview] {platform} {url} {'疑似不适宜内容' if isinstance(e, RestrictedBlocked) else '命中屏蔽词'}，已拦截")
                if not quiet or _bool(self.config.get("block_notice", True), True):
                    yield event.plain_result(e.notice or BLOCK_NOTICE)
                continue
            except Exception as e:
                logger.warning(f"[LinkPreview] {platform} {url} 预览失败：{e}")
                if not quiet:
                    yield event.plain_result(f"预览失败：{e}")
                continue
            if not path:
                continue
            self._last_link[session] = (platform, url)
            image = Comp.Image.fromURL(path) if str(path).startswith("http") else Comp.Image.fromFileSystem(path)
            if not await self._send_or_notice(event, [image]):
                yield event.plain_result(SEND_FAIL_NOTICE)

    # ------------------------------------------------------------------ 自动识别

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def on_message(self, event: AstrMessageEvent):
        text = (event.message_str or "").strip()
        if self._is_command(text) or not self._allowed(event):
            return
        if "http" not in text.lower() and not any(isinstance(s, Comp.Json) for s in event.get_messages() or []):
            return
        limit = _int(self.config.get("max_links_per_message", 2), 2, 1, 5)
        found = fetchers.find_links(self._message_text(event), self._platforms(), limit)
        session = event.unified_msg_origin
        links = []
        for p, u in found:
            if self._duplicate(session, u):
                logger.info(f"[LinkPreview] 跳过重复链接：{u}")
            else:
                links.append((p, u))
        if not links:
            return
        logger.info(f"[LinkPreview] 自动预览 {len(links)} 条：" + " | ".join(u for _, u in links))
        async for res in self._preview(event, links):
            yield res

    # ------------------------------------------------------------------ 发送前检查

    @staticmethod
    def _chain_text(chain):
        """取出消息链里所有文字，包括合并转发节点里的。"""
        parts = []
        for comp in chain or []:
            if isinstance(comp, Comp.Plain):
                parts.append(comp.text or "")
            elif isinstance(comp, Comp.Nodes):
                parts.append(LinkPreviewPlugin._chain_text(comp.nodes))
            elif isinstance(comp, Comp.Node):
                parts.append(LinkPreviewPlugin._chain_text(comp.content))
        return "\n".join(p for p in parts if p)

    @filter.on_decorating_result(priority=-1000)
    async def guard_outgoing(self, event: AstrMessageEvent):
        """机器人自己要发的消息（大模型回复、其他插件的文字）含屏蔽词就不发。

        放在发送前处理的最后一步，检查的是其他插件加工完的最终文字。
        直接调用平台接口发的消息（比如部分插件的主动消息）不经过这里，管不到。
        """
        if not (self._block_on() and _bool(self.config.get("block_outgoing", True), True)):
            return
        result = event.get_result()
        if not result or not result.chain:
            return
        text = self._chain_text(result.chain)
        restricted_hit = _bool(self.config.get("restricted_outgoing", False)) and self.restricted.find(text)
        if text and (self.filter.find(text) or restricted_hit):
            logger.info(f"[LinkPreview] 拦下一条含屏蔽词的回复，不发送（{event.unified_msg_origin}）")
            if _bool(self.config.get("block_notice", True), True):
                result.chain = [Comp.Plain(REPLY_BLOCK_NOTICE)]
            else:
                event.clear_result()
            event.stop_event()

    # ------------------------------------------------------------------ 指令

    @filter.command("预览帮助", alias={"previewhelp"})
    async def preview_help(self, event: AstrMessageEvent):
        yield event.plain_result(HELP)

    @filter.command("预览图片", alias={"previewimg", "预览配图"})
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def image_switch_cmd(self, event: AstrMessageEvent):
        """本群卡片是否显示配图和封面（作者头像不受影响）。"""
        parts = (event.message_str or "").strip().split(maxsplit=1)
        arg = parts[1].strip().lower() if len(parts) > 1 else ""
        session = event.unified_msg_origin
        if arg in ("开", "开启", "打开", "on", "1", "true"):
            self._img_switch[session] = True
        elif arg in ("关", "关闭", "off", "0", "false"):
            self._img_switch[session] = False
        elif arg in ("默认", "重置", "reset", "default"):
            self._img_switch.pop(session, None)
        elif arg:
            yield event.plain_result("用法：/预览图片 开 | 关 | 默认（不带参数查看当前状态）")
            return
        if arg:
            try:
                self._img_file.write_text(json.dumps(self._img_switch, ensure_ascii=False), encoding="utf-8")
            except OSError as e:
                logger.error(f"[LinkPreview] 保存配图开关失败：{e}")
        state = "显示" if self._show_images(session) else "不显示"
        source = "本群设置" if session in self._img_switch else "跟随全局配置"
        yield event.plain_result(f"本群预览卡片现在{state}配图和封面（{source}）。")

    @filter.command("预览", alias={"preview"})
    async def preview_cmd(self, event: AstrMessageEvent):
        """手动预览：任何 http 链接都试一试，不受平台开关限制。"""
        links = self._links_from_command(event)
        if not links:
            yield event.plain_result("用法：/预览 链接")
            return
        async for res in self._preview(event, links[:3], quiet=False):
            yield res

    @filter.command("评论", alias={"comments", "看评论"})
    async def comments_cmd(self, event: AstrMessageEvent):
        """单独出一张评论卡；不带链接时用本群最近预览的那条。"""
        links = self._links_from_command(event)
        if not links:
            last = self._last_link.get(event.unified_msg_origin)
            if not last:
                yield event.plain_result("用法：/评论 链接（本群最近没有预览过链接）")
                return
            links = [last]
        async for res in self._preview(event, links[:1], comments_mode=True, quiet=False):
            yield res

    async def _render_article(self, platform, url):
        """维基百科 / 维基文库全文：抓取、分页、逐页渲染，返回 (图片路径列表, 词条信息, 发出的页数, 没发出的页数)。"""
        page_chars = _int(self.config.get("full_page_chars", 3500), 3500, 1000, 8000)
        max_pages = _int(self.config.get("full_max_pages", 15), 15, 1, 40)
        timeout = _int(self.config.get("fetch_timeout", 12), 12, 3, 60)
        async with fetchers.make_client(self.config.get("proxy") or None, timeout) as client:
            if platform == "wikisource":
                article = await fetchers.fetch_wikisource_full(client, url)
            else:
                article = await fetchers.fetch_wikipedia_full(client, url)
            article = self._filter_article(article)
            pages = fetchers.paginate(article["sections"], page_chars)
            article = await render.prepare_article(client, article)
        if not pages:
            raise fetchers.FetchError("这个词条没有正文")
        hidden = max(0, len(pages) - max_pages)
        pages = pages[:max_pages]
        theme = self.config.get("theme", "dark")
        stem = hashlib.md5(f"{url}|{time.time()}".encode()).hexdigest()[:12]
        paths = []
        for no, blocks in enumerate(pages, 1):
            out = self.cache_dir / f"{stem}-{no:02d}.jpg"
            paths.append(await self._render_page(article, blocks, no, len(pages), hidden, theme, out))
        return paths, article, len(pages), hidden

    @filter.command("翻译", alias={"translate", "翻译帖子"})
    async def translate_cmd(self, event: AstrMessageEvent):
        """翻译链接的标题和正文，出一张带译文的卡片。"""
        links = self._links_from_command(event)
        if not links:
            last = self._last_link.get(event.unified_msg_origin)
            if last:
                links = [last]
        if not links:
            yield event.plain_result("用法：/翻译 链接（也可以先发一次链接，再发 /翻译）")
            return

        async for res in self._preview(event, links[:1], quiet=False, translate=True):
            yield res

    @filter.command("全文", alias={"fulltext", "维基全文"})
    async def fulltext_cmd(self, event: AstrMessageEvent):
        """维基词条全文：按章节分页渲染，合并转发发出。"""
        links = fetchers.find_links(self._message_text(event), {"wikipedia": True, "wikisource": True}, 1)
        if not links:
            last = self._last_link.get(event.unified_msg_origin)
            if last and last[0] in ("wikipedia", "wikisource"):
                links = [last]
        if not links:
            yield event.plain_result("用法：/全文 维基百科或维基文库链接（不带链接时用本群最近预览过的那条）")
            return
        platform, url = links[0]
        self._clean_cache()
        try:
            paths, article, total, hidden = await self._render_article(platform, url)
        except Blocked as e:
            logger.info(f"[LinkPreview] 全文 {url} {'疑似不适宜内容' if isinstance(e, RestrictedBlocked) else '命中屏蔽词'}，已拦截")
            yield event.plain_result(e.notice or BLOCK_NOTICE)
            return
        except Exception as e:
            logger.info(f"[LinkPreview] 维基全文失败 {url}：{e}")
            yield event.plain_result(f"获取全文失败：{e}")
            return
        self._last_link[event.unified_msg_origin] = (platform, url)
        if event.get_platform_name() != "aiocqhttp":
            # 只有 QQ（OneBot）支持合并转发，其他平台逐张发
            for p in paths:
                yield event.image_result(p)
            return
        bot = str(event.get_self_id() or "0")
        head = f"{article['title']}\n{url}\n共 {total} 页"
        if hidden:
            head += f"（还有 {hidden} 页没有发出，完整内容看原文）"
        sender = "维基文库" if platform == "wikisource" else "维基百科"
        if article.get("byline"):
            head = head.replace("\n", f"\n{article['byline']}\n", 1)
        nodes = [Comp.Node(uin=bot, name=sender, content=[Comp.Plain(head)])]
        nodes += [Comp.Node(uin=bot, name=sender, content=[Comp.Image.fromFileSystem(p)]) for p in paths]
        if not await self._send_or_notice(event, [Comp.Nodes(nodes)]):
            yield event.plain_result("全文发送失败（可能被 QQ 拦截了），请直接点链接查看。")

    def _links_from_command(self, event):
        text = self._message_text(event)
        everything = {k: True for k in fetchers.PLATFORMS}
        links = fetchers.find_links(text, everything, 3)
        if links:
            return links
        # 不在已知平台列表里的网址按普通网页处理
        return [("web", u.rstrip(".,;:!?)）】」")) for u in fetchers.URL_RE.findall(text)][:3]
