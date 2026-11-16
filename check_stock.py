import json
import os
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

URL = os.environ["PRODUCT_URL"]
KEYWORD = os.environ["PRODUCT_KEYWORD"]  # 商品名稱中的一段文字,用來確認頁面真的載入成功
SOLD_OUT_TEXT = os.environ.get("SOLD_OUT_TEXT", "售完")
LINE_TOKEN = os.environ["LINE_CHANNEL_ACCESS_TOKEN"]
LINE_USER_ID = os.environ["LINE_USER_ID"]

STATE_FILE = Path("state.txt")


def get_status() -> str:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(locale="zh-TW")
        page.goto(URL, wait_until="networkidle", timeout=60000)
        page.wait_for_timeout(3000)
        text = page.inner_text("body")
        browser.close()

    if KEYWORD not in text:
        return "unknown"  # 頁面被擋或沒載入,不判斷
    return "sold_out" if SOLD_OUT_TEXT in text else "in_stock"


def push_line(message: str) -> None:
    req = urllib.request.Request(
        "https://api.line.me/v2/bot/message/push",
        data=json.dumps(
            {"to": LINE_USER_ID, "messages": [{"type": "text", "text": message}]}
        ).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {LINE_TOKEN}",
        },
        method="POST",
    )
    urllib.request.urlopen(req, timeout=30)


def main() -> None:
    prev = STATE_FILE.read_text().strip() if STATE_FILE.exists() else "sold_out"
    now = get_status()
    print(f"previous={prev} now={now}")

    if now == "unknown":
        return

    if now == "in_stock" and prev != "in_stock":
        push_line(f"🔔 補貨通知!\n{KEYWORD} 好像補貨了\n{URL}")

    STATE_FILE.write_text(now)


if __name__ == "__main__":
    main()
