"""
AlwaysWonder 官網 (alwayswonder-co.com) 新品追蹤器
用 Shopify 公開的 products.json API 抓取全店商品清單，
跟上次抓到的清單比對，出現新的 product id 就發通知（Telegram + LINE 都發）。
"""

import json
import os
from pathlib import Path

import requests

SHOP_URL = "https://alwayswonder-co.com"
STATE_FILE = Path("state_website.json")

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; ProductTracker/1.0)"}

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")


def fetch_all_products():
    products = {}
    page = 1
    while True:
        url = f"{SHOP_URL}/products.json?limit=250&page={page}"
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
        data = resp.json().get("products", [])
        if not data:
            break
        for p in data:
            pid = str(p["id"])
            products[pid] = {
                "title": p.get("title", ""),
                "handle": p.get("handle", ""),
                "createdAt": p.get("created_at", ""),
                "url": f"{SHOP_URL}/products/{p.get('handle', '')}",
            }
        page += 1
        if page > 20:
            break
    return products


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


def main():
    old_state = load_previous_state()
    is_first_run = not old_state

    new_state = fetch_all_products()

    new_products = [
        (pid, info) for pid, info in new_state.items() if pid not in old_state
    ]

    if is_first_run:
        print(f"第一次執行，建立基準資料：{len(new_state)} 個商品。不發送通知。")
    else:
        for pid, info in new_products:
            msg = (
                f"🆕 官網新品上架！\n"
                f"{info['title']}\n"
                f"{info['url']}"
            )
            notify(msg)

        if not new_products:
            print("本次沒有偵測到新商品。")

    save_state(new_state)


if __name__ == "__main__":
    main()
