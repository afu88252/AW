import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

# ===== 只需要改這裡 =====
STORE_URL = "https://shop.line.me/@mybabygirl.club"
SOLD_OUT_WORDS = ["sold out", "售完", "完售", "缺貨"]
# ========================

LINE_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "").strip()
LINE_USER_ID = os.environ.get("LINE_USER_ID", "").strip()
STATE_FILE = Path("store_state.json")

if not LINE_TOKEN or not LINE_USER_ID:
    sys.exit("錯誤:缺少 LINE_CHANNEL_ACCESS_TOKEN 或 LINE_USER_ID,請到 Settings > Secrets 新增")


def scrape() -> dict:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(locale="zh-TW")
        page.goto(STORE_URL, wait_until="networkidle", timeout=60000)
        page.wait_for_timeout(3000)
        for _ in range(10):
            page.mouse.wheel(0, 4000)
            page.wait_for_timeout(1000)
        raw = page.eval_on_selector_all(
            'a[href*="/product/"]',
            "els => els.map(e => ({href: e.href, text: e.innerText}))",
        )
        browser.close()

    items = {}
    for r in raw:
        url = r["href"].split("?")[0]
        text = " ".join(r["text"].split())
        sold_out = any(w.lower() in text.lower() for w in SOLD_OUT_WORDS)
        if url not in items or (text and not items[url]["title"]):
            items[url] = {"title": text[:40] if text else url, "sold_out": sold_out}
    return items


def push_line(message: str) -> None:
    req = urllib.request.Request(
        "https://api.line.me/v2/bot/message/push",
        data=json.dumps(
            {"to": LINE_USER_ID, "messages": [{"type": "text", "text": message[:4500]}]}
        ).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {LINE_TOKEN}",
        },
        method="POST",
    )
    try:
        urllib.request.urlopen(req, timeout=30)
    except urllib.error.HTTPError as e:
        print("LINE 回傳錯誤:", e.code, e.read().decode("utf-8", "ignore"))
        raise


def main() -> None:
    current = scrape()
    sold = sum(1 for v in current.values() if v["sold_out"])
    print(f"found {len(current)} products, {sold} sold out")

    if not current:
        print("沒抓到任何商品,不更新狀態")
        return

    if not STATE_FILE.exists():
        push_line(f"✅ 已開始監控店家,目前記錄到 {len(current)} 件商品(其中 {sold} 件售完)。之後有新品或補貨會通知你。")
        STATE_FILE.write_text(json.dumps(current, ensure_ascii=False, indent=1))
        return

    prev = json.loads(STATE_FILE.read_text())
    lines = []
    for url, v in current.items():
        if url not in prev:
            lines.append(f"🆕 新上架:{v['title']}\n{url}")
        elif prev[url]["sold_out"] and not v["sold_out"]:
            lines.append(f"🔔 補貨:{v['title']}\n{url}")

    if lines:
        push_line("\n\n".join(lines[:10]))

    STATE_FILE.write_text(json.dumps({**prev, **current}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
