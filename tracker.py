"""
LINE SHOPPING 店家新品追蹤器
店家：alwayswonder.co
邏輯：
  1. 用 Playwright 開啟店家首頁，讀出 window.__NUXT__ 裡已經解析好的資料
  2. 取得目前所有「收藏系列」清單
  3. 逐一開啟每個收藏系列頁面，取得該系列底下的商品清單（含上架時間 createdAt）
  4. 跟上次執行存下來的 state.json 比對：
       - 出現沒看過的 collection id -> 新系列上架
       - 出現沒看過的 product id     -> 新商品上架
  5. 有新東西就發 Telegram 訊息通知
  6. 把這次抓到的完整清單存回 state.json（下次比對用）
"""

import asyncio
import json
import os
from pathlib import Path

import requests
from playwright.async_api import async_playwright

SHOP_ALIAS = "@alwayswonder.co"
SHOP_URL = f"https://shop.line.me/{SHOP_ALIAS}"
STATE_FILE = Path("state.json")

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")


async def fetch_nuxt_data(page, url):
    """打開一個頁面，等它載入完成，回傳頁面內解析好的 __NUXT__ 資料"""
    await page.goto(url, wait_until="networkidle", timeout=30000)
    return await page.evaluate("() => window.__NUXT__")


async def get_shop_snapshot():
    """抓取店家目前完整的收藏系列 + 商品清單"""
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()

        home_data = await fetch_nuxt_data(page, SHOP_URL)
        home = home_data.get("data", {})
        collections = home.get(f"shop:{SHOP_ALIAS}:collections", [])

        snapshot = {"collections": {}, "products": {}}

        for col in collections:
            col_id = str(col["id"])
            col_name = col.get("collectionName", "")
            snapshot["collections"][col_id] = col_name

            col_url = f"{SHOP_URL}/collection/{col_id}"
            try:
                col_data = await fetch_nuxt_data(page, col_url)
            except Exception as e:
                print(f"抓取收藏系列 {col_name} ({col_id}) 失敗: {e}")
                continue

            col_detail = col_data.get("data", {}).get(
                f"shop:{SHOP_ALIAS}:collection:{col_id}", {}
            )
            for prod in col_detail.get("products", []):
                pid = str(prod["productId"])
                snapshot["products"][pid] = {
                    "name": prod.get("productName", ""),
                    "collection": col_name,
                    "collectionId": col_id,
                    "createdAt": prod.get("createdAt", ""),
                    "status": prod.get("status", ""),
                }

        await browser.close()
    return snapshot


def load_previous_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {"collections": {}, "products": {}}


def save_state(state):
    STATE_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def send_telegram(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("未設定 TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID，略過通知")
        print("(訊息內容如下)")
        print(message)
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


async def main():
    old_state = load_previous_state()
    is_first_run = not old_state["collections"] and not old_state["products"]

    new_state = await get_shop_snapshot()

    new_collections = [
        (cid, name)
        for cid, name in new_state["collections"].items()
        if cid not in old_state["collections"]
    ]
    new_products = [
        (pid, info)
        for pid, info in new_state["products"].items()
        if pid not in old_state["products"]
    ]

    if is_first_run:
        print(
            f"第一次執行，建立基準資料："
            f"{len(new_state['collections'])} 個系列、"
            f"{len(new_state['products'])} 個商品。不發送通知。"
        )
    else:
        for cid, name in new_collections:
            msg = (
                f"🆕 新收藏系列上架！\n"
                f"{name}\n"
                f"{SHOP_URL}/collection/{cid}"
            )
            send_telegram(msg)

        for pid, info in new_products:
            msg = (
                f"🆕 新商品上架！\n"
                f"{info['name']}\n"
                f"系列：{info['collection']}\n"
                f"{SHOP_URL}/collection/{info['collectionId']}"
            )
            send_telegram(msg)

        if not new_collections and not new_products:
            print("本次沒有偵測到新系列或新商品。")

    save_state(new_state)


if __name__ == "__main__":
    asyncio.run(main())
