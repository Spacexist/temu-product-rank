# -*- coding: utf-8 -*-
"""Temu JP 区域一致的站点入口与 HTTP 头（选品下载/脚本用）。"""

# 日本站英文界面（region=100, currency=JPY）
TEMU_HOME = "https://www.temu.com/jp-en/"

TEMU_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# 与浏览器 JP 站一致：英文 + 日本优先，避免 zh-CN + Asia/Shanghai 与站点错位
TEMU_ACCEPT_LANGUAGE = "en-JP,en;q=0.9,ja;q=0.8"


def temu_aiohttp_headers() -> dict[str, str]:
    return {
        "User-Agent": TEMU_USER_AGENT,
        "Referer": TEMU_HOME,
        "Accept-Language": TEMU_ACCEPT_LANGUAGE,
    }
