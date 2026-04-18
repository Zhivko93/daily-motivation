import hashlib
import json
import os
import random
import re
from pathlib import Path

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.brainyquote.com/topics/motivational-quotes"
HEADERS = {
    "User-Agent": "daily-motivational-quote-bot/1.1"
}

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


def fetch_page(page_number: int) -> str:
    if page_number == 1:
        url = BASE_URL
    else:
        url = f"{BASE_URL}_{page_number}"

    response = requests.get(url, headers=HEADERS, timeout=30)
    response.raise_for_status()
    return response.text


def clean_text(text: str) -> str:
    text = text.replace("\xa0", " ")
    text = text.replace("&#39;", "'")
    text = text.replace("&quot;", '"')
    text = text.replace("&amp;", "&")
    text = text.replace("&#x27;", "'")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def is_valid_author(text: str) -> bool:
    if not text:
        return False
    if len(text) < 2 or len(text) > 60:
        return False
    if any(x in text.lower() for x in ["prev", "next", "grid", "list", "topics", "quotes"]):
        return False
    return True


def is_valid_quote(text: str) -> bool:
    if not text:
        return False
    if len(text) < 15 or len(text) > 400:
        return False
    junk = [
        "please enable javascript",
        "this site requires javascript",
        "quote of the day",
        "recommended topics",
    ]
    if any(x in text.lower() for x in junk):
        return False
    return True


def dedupe_quotes(quotes: list[dict]) -> list[dict]:
    seen = set()
    deduped = []

    for q in quotes:
        fp = quote_fingerprint(q["text"], q["author"])
        if fp in seen:
            continue
        seen.add(fp)
        deduped.append(q)

    return deduped


def extract_quotes_from_html(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")

    # Collect visible anchor text in page order.
    anchors = []
    for a in soup.find_all("a"):
        text = clean_text(a.get_text(" ", strip=True))
        href = a.get("href", "")
        if text:
            anchors.append({"text": text, "href": href})

    quotes = []

    # Heuristic: on the current page, quote text is followed by author text.
    # We treat a longer sentence-like anchor followed by a shorter author-like anchor as a pair.
    for i in range(len(anchors) - 1):
        first = anchors[i]["text"]
        second = anchors[i + 1]["text"]

        if not is_valid_quote(first):
            continue
        if not is_valid_author(second):
            continue

        # Quote should look more sentence-like than author.
        if len(second) >= len(first):
            continue

        # Avoid pairing obvious navigation items.
        if second.lower() in {"home", "authors", "topics"}:
            continue

        quotes.append({
            "text": first.strip(" “”\""),
            "author": second.strip(),
        })

    return dedupe_quotes(quotes)


def collect_quotes(max_pages: int = 5) -> list[dict]:
    all_quotes = []

    for page_number in range(1, max_pages + 1):
        try:
            html = fetch_page(page_number)
            page_quotes = extract_quotes_from_html(html)
            all_quotes.extend(page_quotes)
        except Exception:
            continue

    all_quotes = dedupe_quotes(all_quotes)

    if not all_quotes:
        raise RuntimeError("No quotes could be collected from BrainyQuote.")

    return all_quotes


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
    quotes = collect_quotes(max_pages=5)
    chosen_quote, fingerprint = pick_unsent_quote(quotes, sent_quotes)

    send_to_discord(webhook_url, chosen_quote)

    sent_quotes.add(fingerprint)
    save_sent_quotes(sent_quotes)


if __name__ == "__main__":
    main()
