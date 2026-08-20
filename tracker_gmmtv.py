"""
GMMTV SHOP (shop.gmm-tv.com) 新品追蹤器
只監控三個指定分類頁：any / jewel / lunar
用 Playwright 抓取每個分類頁所有商品，
跟上次記錄比對，有新商品就發通知。

注意：這個網站商品頁的價格/庫存是動態渲染的，選擇器是推測的，
第一次執行如果抓不到資料或出錯，需要根據實際結果調整。
"""
import asyncio
import json
import os
import re
from pathlib import Path

import requests
from playwright.async_api import async_playwright

BASE_URL = "https://shop.gmm-tv.com"
COLLECTION_URLS = [
    f"{BASE_URL}/collections/any",
    f"{BASE_URL}/collections/jewel",
    f"{BASE_URL}/collections/lunar",
]
STATE_FILE = Path("state_gmmtv.json")

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")

STOCK_KEYWORDS = ["SOLD OUT", "OUT OF STOCK", "PRE-ORDER", "PREORDER", "COMING SOON"]


async def get_product_links(page, collection_url):
    """從分類頁抓出所有商品連結"""
    await page.goto(collection_url, wait_until="domcontentloaded", timeout=45000)
    await page.wait_for_timeout(3000)
    links = await page.eval_on_selector_all(
        "a[href*='/product/']",
        "els => [...new Set(els.map(e => e.href))]",
    )
    return links


async def get_product_detail(page, url):
    """進入商品頁，抓名稱、價格、庫存狀態"""
    await page.goto(url, wait_until="domcontentloaded", timeout=45000)
    await page.wait_for_timeout(2000)

    name = await page.title()
    name = name.replace("| GMMTV SHOP", "").replace("GMMTV SHOP", "").strip(" |-")

    # 嘗試抓價格
    price = ""
    for selector in [".price", "[class*='price']"]:
        try:
            el = await page.query_selector(selector)
            if el:
                price = (await el.inner_text()).strip()
                break
        except Exception:
            pass

    # 掃整頁文字找庫存狀態關鍵字
    stock_status = "AVAILABLE"
    try:
        body_text = (await page.inner_text("body")).upper()
        for keyword in STOCK_KEYWORDS:
            if keyword in body_text:
                stock_status = keyword
                break
    except Exception:
        pass

    return {
        "name": name,
        "url": url,
        "price": price,
        "stock_status": stock_status,
    }


async def get_snapshot():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()

        all_links = set()
        for collection_url in COLLECTION_URLS:
            try:
                links = await get_product_links(page, collection_url)
                print(f"{collection_url} 抓到 {len(links)} 個商品連結")
                all_links.update(links)
            except Exception as e:
                print(f"抓取分類頁失敗 {collection_url}: {e}")

        print(f"合併去重後共 {len(all_links)} 個商品")

        snapshot = {}
        for url in all_links:
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

    for url, info in new_products:
        msg = (
            f"🆕 GMMTV SHOP 新商品上架！\n"
            f"{info['name']}\n"
            f"{info['price']}\n"
            f"{url}"
        )
        notify(msg)

    if not new_products:
        print("本次沒有偵測到新商品。")

    save_state(new_state)


if __name__ == "__main__":
    asyncio.run(main())
