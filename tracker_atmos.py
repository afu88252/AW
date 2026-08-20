"""
atmos-tokyo.com 特定商品庫存追蹤器
只監控指定的商品網址，偵測「尺寸從缺貨變有貨」就發通知（補貨提醒）。

追蹤商品清單見 PRODUCT_URLS。
注意：庫存狀態是動態渲染的，選擇器是推測的，
第一次執行如果抓不到資料或出錯，需要根據實際結果調整。
"""
import asyncio
import json
import os
from pathlib import Path

import requests
from playwright.async_api import async_playwright

PRODUCT_URLS = [
    "https://www.atmos-tokyo.com/item/brand/mabsu-ac049",
    "https://www.atmos-tokyo.com/item/atmosapparel/mabfa-ts135-blk",
]
STATE_FILE = Path("state_atmos.json")

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")


async def get_product_stock(page, url):
    """進入商品頁，點開尺寸選單，抓每個尺寸是否有貨"""
    await page.goto(url, wait_until="domcontentloaded", timeout=45000)
    await page.wait_for_timeout(2000)

    name = await page.title()
    name = name.split("|")[0].strip()

    # 點擊「サイズを選択」開啟尺寸選單
    try:
        size_trigger = page.get_by_text("サイズを選択", exact=False)
        if await size_trigger.count() > 0:
            await size_trigger.first.click(timeout=5000)
            await page.wait_for_timeout(1500)
    except Exception as e:
        print(f"  點擊尺寸選單失敗（可能只有單一規格）: {e}")

    # 抓尺寸選項與是否可選（有貨）
    # 常見結構：每個尺寸是一個 button/li，缺貨的會有 disabled 屬性或特定 class
    sizes = {}
    for selector in [
        "button[class*='size']",
        "li[class*='size']",
        "[class*='sizeList'] li",
        "[class*='sizeList'] button",
        "button",
    ]:
        try:
            els = await page.query_selector_all(selector)
            if not els or len(els) > 100:
                continue
            candidates = {}
            for el in els:
                text = (await el.inner_text()).strip()
                if not text or len(text) > 20:
                    continue
                is_disabled = await el.get_attribute("disabled") is not None
                class_name = (await el.get_attribute("class")) or ""
                looks_soldout = (
                    is_disabled
                    or "disabled" in class_name.lower()
                    or "soldout" in class_name.lower()
                    or "sold-out" in class_name.lower()
                )
                candidates[text] = "在庫あり" if not looks_soldout else "在庫なし"
            # 篩選出像尺寸代碼的項目 (S, M, L, XL, FREE, 数字等)
            size_like = {
                k: v for k, v in candidates.items()
                if len(k) <= 6
            }
            if len(size_like) >= 1:
                sizes = size_like
                break
        except Exception:
            pass

    return {
        "name": name,
        "url": url,
        "sizes": sizes,
    }


async def get_snapshot():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()

        snapshot = {}
        for url in PRODUCT_URLS:
            try:
                info = await get_product_stock(page, url)
                snapshot[url] = info
                print(f"{url} -> {info['sizes']}")
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
        print("第一次執行，建立基準庫存資料。不發送通知。")
        save_state(new_state)
        return

    restock_alerts = []
    for url, info in new_state.items():
        old_sizes = old_state.get(url, {}).get("sizes", {})
        new_sizes = info.get("sizes", {})
        for size, status in new_sizes.items():
            old_status = old_sizes.get(size)
            if status == "在庫あり" and old_status != "在庫あり":
                restock_alerts.append((info["name"], size, url))

    for name, size, url in restock_alerts:
        msg = (
            f"🔔 補貨通知！\n"
            f"{name}\n"
            f"尺寸：{size} 現在有貨\n"
            f"{url}"
        )
        notify(msg)

    if not restock_alerts:
        print("本次沒有偵測到補貨。")

    save_state(new_state)


if __name__ == "__main__":
    asyncio.run(main())
