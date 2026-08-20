"""
KEEPSILENT (keepsilentshhh.com) 新品／尺寸更新追蹤器
用 Playwright 抓取 /category 頁面所有商品，
再逐一進入商品頁抓尺寸選項，
跟上次記錄比對，有新商品或尺寸變動就發通知。

注意：這個網站沒有公開 API，選擇器是根據常見電商網站結構推測，
第一次執行如果抓不到資料或出錯，需要根據實際錯誤訊息調整。
"""
import asyncio
import json
import os
import re
from pathlib import Path

import requests
from playwright.async_api import async_playwright

BASE_URL = "https://www.keepsilentshhh.com"
CATEGORY_URL = f"{BASE_URL}/category"
STATE_FILE = Path("state_keepsilent.json")

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")


async def get_product_links(page):
    """從分類頁抓出所有商品連結"""
    await page.goto(CATEGORY_URL, wait_until="domcontentloaded", timeout=45000)
    # 網頁用 JS 動態載入商品，等待畫面實際渲染出來
    await page.wait_for_timeout(3000)
    # LnwX 商品連結通常包含 /product/ 路徑，用這個規則抓連結
    links = await page.eval_on_selector_all(
        "a[href*='/product/']",
        "els => [...new Set(els.map(e => e.href))]",
    )
    return links


SIZE_TOKEN_PATTERN = re.compile(r"SIZE\s+([A-Z0-9]{1,4})\s*[:\-]", re.IGNORECASE)


async def get_product_detail(page, url):
    """進入商品頁，抓名稱、價格、meta 描述裡的尺寸資訊"""
    await page.goto(url, wait_until="domcontentloaded", timeout=45000)
    await page.wait_for_timeout(2000)

    name = await page.title()
    name = name.replace("KEEPSILENT", "").strip(" |-")

    # 嘗試抓價格（常見 class 名稱，抓不到就留空）
    price = ""
    for selector in [".price", ".product-price", "[class*='price']"]:
        try:
            el = await page.query_selector(selector)
            if el:
                price = (await el.inner_text()).strip()
                break
        except Exception:
            pass

    # 尺寸資訊藏在 meta description（網站固定寫在裡面的尺寸表），
    # 例如："SIZE S : CHEST 44 SIZE M : CHEST 46 SIZE L : CHEST 48"
    sizes = []
    try:
        meta_desc = await page.get_attribute(
            "meta[property='og:description']", "content"
        )
        if not meta_desc:
            meta_desc = await page.get_attribute(
                "meta[name='description']", "content"
            )
        if meta_desc:
            sizes = sorted(set(m.upper() for m in SIZE_TOKEN_PATTERN.findall(meta_desc)))
    except Exception:
        pass

    return {
        "name": name,
        "url": url,
        "price": price,
        "sizes": sizes,
    }


async def get_snapshot():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()

        links = await get_product_links(page)
        print(f"分類頁抓到 {len(links)} 個商品連結")

        snapshot = {}
        for url in links:
            try:
                info = await get_product_detail(page, url)
                snapshot[url] = info
            except Exception as e:
                print(f"抓取商品失敗 {url}: {e}")
                continue

        await browser.close()
    return snapshot


def load_previous_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {}


def save_state(state):
    STATE_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def send_telegram(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("未設定 TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID，略過 Telegram 通知")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    resp = requests.post(
        url,
        data={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "disable_web_page_preview": False,
        },
        timeout=15,
    )
    if resp.status_code != 200:
        print("Telegram 發送失敗:", resp.status_code, resp.text)
    else:
        print("Telegram 通知已送出")


def send_line(message):
    if not LINE_CHANNEL_ACCESS_TOKEN:
        print("未設定 LINE_CHANNEL_ACCESS_TOKEN，略過 LINE 通知")
        return
    url = "https://api.line.me/v2/bot/message/broadcast"
    headers = {
        "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }
    body = {"messages": [{"type": "text", "text": message[:5000]}]}
    resp = requests.post(url, headers=headers, json=body, timeout=15)
    if resp.status_code != 200:
        print("LINE 發送失敗:", resp.status_code, resp.text)
    else:
        print("LINE 通知已送出")


def notify(message):
    send_telegram(message)
    send_line(message)


async def main():
    old_state = load_previous_state()
    is_first_run = not old_state

    new_state = await get_snapshot()

    if is_first_run:
        print(f"第一次執行，建立基準資料：{len(new_state)} 個商品。不發送通知。")
        save_state(new_state)
        return

    new_products = [
        (url, info) for url, info in new_state.items() if url not in old_state
    ]

    size_updates = []
    for url, info in new_state.items():
        if url in old_state:
            old_sizes = set(old_state[url].get("sizes", []))
            new_sizes = set(info.get("sizes", []))
            added_sizes = new_sizes - old_sizes
            if added_sizes:
                size_updates.append((url, info, added_sizes))

    for url, info in new_products:
        msg = (
            f"🆕 新商品上架！\n"
            f"{info['name']}\n"
            f"{info['price']}\n"
            f"尺寸：{', '.join(info['sizes']) if info['sizes'] else '未知'}\n"
            f"{url}"
        )
        notify(msg)

    for url, info, added_sizes in size_updates:
        msg = (
            f"📦 尺寸更新！\n"
            f"{info['name']}\n"
            f"新增尺寸：{', '.join(sorted(added_sizes))}\n"
            f"{url}"
        )
        notify(msg)

    if not new_products and not size_updates:
        print("本次沒有偵測到新商品或尺寸更新。")

    save_state(new_state)


if __name__ == "__main__":
    asyncio.run(main())
