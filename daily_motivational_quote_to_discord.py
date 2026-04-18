import hashlib
import json
import os
import random
from pathlib import Path

import requests
from playwright.sync_api import sync_playwright

BASE_URL = "https://www.brainyquote.com/topics/motivational-quotes"
STATE_FILE = Path("sent_quotes.json")


def get_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def load_sent_quotes() -> set[str]:
    if not STATE_FILE.exists():
        return set()

    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return set(str(x) for x in data)
    except Exception:
        pass

    return set()


def save_sent_quotes(sent_quotes: set[str]) -> None:
    STATE_FILE.write_text(
        json.dumps(sorted(sent_quotes), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def quote_fingerprint(text: str, author: str) -> str:
    normalized = f"{author.strip()}|{text.strip()}".lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def clean_text(text: str) -> str:
    return " ".join(text.replace("\xa0", " ").split()).strip()


def is_valid_quote(text: str) -> bool:
    if not text:
        return False
    if len(text) < 15 or len(text) > 400:
        return False

    junk = [
        "motivational quotes",
        "quote of the day",
        "brainyquote",
        "authors",
        "topics",
        "menu",
        "home",
        "popular authors",
        "recommended topics",
        "please enable javascript",
    ]
    lower = text.lower()
    if any(x in lower for x in junk):
        return False

    return True


def is_valid_author(text: str) -> bool:
    if not text:
        return False
    if len(text) < 2 or len(text) > 60:
        return False

    lower = text.lower()
    junk = [
        "motivational quotes",
        "quote of the day",
        "brainyquote",
        "authors",
        "topics",
        "menu",
        "home",
        "popular authors",
        "recommended topics",
        "prev",
        "next",
    ]
    if any(x == lower for x in junk):
        return False

    if text.endswith(".") or text.endswith("!") or text.endswith("?"):
        return False

    return True


def extract_quotes_with_playwright(max_pages: int = 5) -> list[dict]:
    quotes = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 2200})

        for page_number in range(1, max_pages + 1):
            if page_number == 1:
                url = BASE_URL
            else:
                url = f"{BASE_URL}_{page_number}"

            page.goto(url, wait_until="networkidle", timeout=60000)
            page.wait_for_timeout(3000)

            # Grab visible text blocks from the rendered page
            texts = page.locator("a, div, span").all_inner_texts()
            texts = [clean_text(t) for t in texts if clean_text(t)]

            # Heuristic: quote followed by author
            for i in range(len(texts) - 1):
                quote_text = texts[i]
                author = texts[i + 1]

                if not is_valid_quote(quote_text):
                    continue
                if not is_valid_author(author):
                    continue

                if len(author) >= len(quote_text):
                    continue

                quotes.append({
                    "text": quote_text.strip('“”" '),
                    "author": author.strip(),
                })

        browser.close()

    # dedupe
    deduped = []
    seen = set()
    for q in quotes:
        fp = quote_fingerprint(q["text"], q["author"])
        if fp in seen:
            continue
        seen.add(fp)
        deduped.append(q)

    if not deduped:
        raise RuntimeError("No quotes could be collected from BrainyQuote.")

    return deduped


def pick_unsent_quote(quotes: list[dict], sent_quotes: set[str]) -> tuple[dict, str]:
    unsent = []

    for quote in quotes:
        fp = quote_fingerprint(quote["text"], quote["author"])
        if fp not in sent_quotes:
            unsent.append((quote, fp))

    if not unsent:
        raise RuntimeError("All collected quotes have already been sent.")

    return random.choice(unsent)


def send_to_discord(webhook_url: str, quote: dict) -> None:
    message = f'💬 **Daily motivational quote**\n\n"{quote["text"]}"\n— *{quote["author"]}*'

    response = requests.post(
        webhook_url,
        data={"content": message},
        timeout=60,
    )

    if response.status_code >= 300:
        raise RuntimeError(f"Discord webhook error: {response.status_code} {response.text}")


def main() -> None:
    webhook_url = get_env("DISCORD_QUOTES_WEBHOOK_URL")

    sent_quotes = load_sent_quotes()
    quotes = extract_quotes_with_playwright(max_pages=5)
    chosen_quote, fingerprint = pick_unsent_quote(quotes, sent_quotes)

    send_to_discord(webhook_url, chosen_quote)

    sent_quotes.add(fingerprint)
    save_sent_quotes(sent_quotes)


if __name__ == "__main__":
    main()
