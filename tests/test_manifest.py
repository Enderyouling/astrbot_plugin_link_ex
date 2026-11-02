"""清单与配置校验：防止发布包缺文件、配置项写错、文档与代码脱节。

只做静态检查，不联网、不需要 AstrBot。
"""

import json
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as f:
        return f.read()


class TestMetadata(unittest.TestCase):
    def setUp(self):
        self.text = read("metadata.yaml")

    def test_required_fields(self):
        for key in ("name:", "display_name:", "short_desc:", "desc:", "version:", "author:", "repo:"):
            self.assertIn(key, self.text, f"metadata.yaml 缺少 {key}")

    def test_name_matches_repo_dir(self):
        m = re.search(r"^name:\s*(\S+)", self.text, re.M)
        self.assertEqual(m.group(1), "astrbot_plugin_link_ex")
        self.assertIn(f'PLUGIN_NAME = "{m.group(1)}"', read("main.py"))

    def test_version_format(self):
        m = re.search(r"^version:\s*(\S+)", self.text, re.M)
        self.assertRegex(m.group(1), r"^\d+\.\d+\.\d+$")

    def test_astrbot_version_range(self):
        self.assertIn("astrbot_version:", self.text)


class TestConfigSchema(unittest.TestCase):
    def setUp(self):
        self.schema = json.loads(read("_conf_schema.json"))

    def test_every_item_has_type_and_description(self):
        for key, item in self.schema.items():
            self.assertIn("type", item, f"{key} 缺少 type")
            self.assertIn("description", item, f"{key} 缺少 description")
            # object 类型（如 platforms）由 items 描述子项，本身不需要 default
            if item["type"] != "object":
                self.assertIn("default", item, f"{key} 缺少 default")

    def test_bool_defaults_are_bool(self):
        for key, item in self.schema.items():
            if item["type"] == "bool":
                self.assertIsInstance(item["default"], bool, f"{key} 默认值不是 bool")

    def test_platform_items_have_bool_default(self):
        items = self.schema["platforms"]["items"]
        for key, item in items.items():
            self.assertEqual(item["type"], "bool", f"平台 {key} 不是 bool")
            self.assertIsInstance(item["default"], bool, f"平台 {key} 默认值不是 bool")

    def test_wordlist_defaults_stay_inside_plugin_data(self):
        """市场审核要求：持久化文件不能落在插件数据目录之外。"""
        for key in ("block_words_file", "restricted_words_file"):
            default = self.schema[key]["default"]
            self.assertEqual(default, "", f"{key} 默认值应为空串，留空才走插件数据目录")

    def test_no_removed_keys(self):
        for key in ("x_login_url", "instagram_cookie"):
            self.assertNotIn(key, self.schema, f"{key} 已移除，不该再出现在配置里")

    def test_no_adult_keywords_in_schema(self):
        """配置项和文案里不要出现成人相关字样，避免仓库被判定为成人内容。"""
        text = read("_conf_schema.json").lower()
        for word in ("r18", "r-18", "成人", "色情", "nsfw", "porn", "adult"):
            self.assertNotIn(word, text, f"_conf_schema.json 里还有 {word}")


class TestPackaging(unittest.TestCase):
    def test_required_files_present(self):
        for name in ("main.py", "fetchers.py", "render.py", "wordfilter.py", "requirements.txt",
                     "metadata.yaml", "_conf_schema.json", "LICENSE", "README.md",
                     "templates/card.html", "templates/article.html",
                     "sensitive_words.txt", "restricted_words.txt"):
            self.assertTrue(os.path.exists(os.path.join(ROOT, name)), f"缺少 {name}")

    def test_requirements_cover_imports(self):
        req = read("requirements.txt").lower()
        for pkg in ("httpx", "jinja2", "beautifulsoup4", "pillow"):
            self.assertIn(pkg, req, f"requirements.txt 缺少 {pkg}")

    def test_no_playwright_dependency(self):
        """渲染已统一走 AstrBot 的文转图，插件不再需要浏览器。"""
        req = read("requirements.txt").lower()
        self.assertNotIn("playwright", req)
        for name in ("render.py", "main.py"):
            self.assertNotIn("playwright", read(name).lower(), f"{name} 里还有 playwright 引用")

    def test_license_is_mit(self):
        self.assertIn("MIT License", read("LICENSE"))

    # 文档里用于教学演示的假值，允许出现
    FAKE_TOKENS = {"1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b"}

    def test_no_real_credentials_committed(self):
        """别把真实的 X / Instagram 凭据写进仓库（示例必须是假值）。"""
        for name in ("README.md", "main.py", "fetchers.py", "_conf_schema.json"):
            text = read(name)
            for token in re.findall(r"auth_token=\s*([0-9a-f]{32,})", text):
                self.assertIn(token, self.FAKE_TOKENS, f"{name} 里像是有真实 auth_token")
            self.assertNotRegex(text, r"sessionid=\d{6,}%3A", f"{name} 里像是有真实 IG sessionid")

    def test_docker_service_files_present(self):
        base = os.path.join(ROOT, "x-browser-service")
        for name in ("Dockerfile", "compose.yaml", "scraper.py", ".env.example"):
            self.assertTrue(os.path.exists(os.path.join(base, name)), f"缺少 x-browser-service/{name}")


class TestNoAdultKeywords(unittest.TestCase):
    """仓库里对外展示的文本不要出现成人相关字样，避免被判定为成人内容。"""

    WORDS = ("r18", "r-18", "成人", "色情", "nsfw", "porn", "adult", "18+")

    def test_readme(self):
        text = read("README.md").lower()
        for w in self.WORDS:
            self.assertNotIn(w, text, f"README.md 里还有 {w}")

    def test_metadata(self):
        text = read("metadata.yaml").lower()
        for w in self.WORDS:
            self.assertNotIn(w, text, f"metadata.yaml 里还有 {w}")

    def test_schema(self):
        text = read("_conf_schema.json").lower()
        for w in self.WORDS:
            self.assertNotIn(w, text, f"_conf_schema.json 里还有 {w}")


class TestReadme(unittest.TestCase):
    def setUp(self):
        self.text = read("README.md")

    def test_has_disclaimer_and_license(self):
        self.assertIn("免责声明", self.text)
        self.assertIn("许可证", self.text)

    def test_mentions_all_configurable_platforms(self):
        items = json.loads(read("_conf_schema.json"))["platforms"]["items"]
        missing = []
        for key, item in items.items():
            # 中文名（去掉括号里的补充说明）或平台 key 出现一次就算提到
            label = re.split(r"[（(]", item["description"])[0].strip()
            if key.lower() not in self.text.lower() and label not in self.text:
                missing.append(f"{key} / {label}")
        self.assertEqual(missing, [], f"这些平台在 README 里没提到：{missing}")


if __name__ == "__main__":
    unittest.main()
