import hashlib
import json
import os
import random
import re
from pathlib import Path

import requests

BASE_URL = "https://www.brainyquote.com/topics/motivational-quotes"
HEADERS = {
    "User-Agent": "daily-motivational-quote-bot/1.0"
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


def extract_quotes_from_html(html: str) -> list[dict]:
    """
    BrainyQuote page currently contains quote links followed by author links
    in the page HTML. This parser intentionally stays simple and resilient.
    """
    results = []

    pattern = re.compile(
        r'【\d+†\s*(.*?)\s*】\s*【\d+†(.*?)】',
        re.DOTALL,
    )

    # Also support raw HTML fallback if needed
    if "【" in html and "†" in html:
        pairs = pattern.findall(html)
        for quote_text, author in pairs:
            quote_text = clean_text(quote_text)
            author = clean_text(author)

            if not is_valid_quote(quote_text, author):
                continue

            results.append({"text": quote_text, "author": author})

        return dedupe_quotes(results)

    # Raw HTML parsing fallback
    # Quote links often appear as title text inside anchor tags with the author nearby.
    quote_pattern = re.compile(
        r'<a[^>]*title="view quote"[^>]*>(.*?)</a>\s*<a[^>]*title="view author"[^>]*>(.*?)</a>',
        re.DOTALL | re.IGNORECASE,
    )

    for quote_text, author in quote_pattern.findall(html):
        quote_text = clean_text(strip_tags(quote_text))
        author = clean_text(strip_tags(author))

        if not is_valid_quote(quote_text, author):
            continue

        results.append({"text": quote_text, "author": author})

    return dedupe_quotes(results)


def strip_tags(text: str) -> str:
    text = re.sub(r"<.*?>", "", text, flags=re.DOTALL)
    return text


def clean_text(text: str) -> str:
    text = text.replace("&#39;", "'")
    text = text.replace("&quot;", '"')
    text = text.replace("&amp;", "&")
    text = text.replace("&#x27;", "'")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def is_valid_quote(quote_text: str, author: str) -> bool:
    if not quote_text or not author:
        return False
    if len(quote_text) < 15:
        return False
    if len(quote_text) > 400:
        return False
    if author.lower() in {"grid", "list", "prev", "next"}:
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
