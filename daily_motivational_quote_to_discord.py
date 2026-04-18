import hashlib
import json
import os
import random
from pathlib import Path

import requests

QUOTABLE_RANDOM_URL = "https://api.quotable.io/quotes/random"
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


def fetch_random_quotes(limit: int = 20) -> list[dict]:
    params = {
        "limit": limit,
        "tags": "inspirational|wisdom|success",
        "maxLength": 180,
    }

    response = requests.get(QUOTABLE_RANDOM_URL, params=params, timeout=30)
    response.raise_for_status()
    data = response.json()

    if not isinstance(data, list) or not data:
        raise RuntimeError("No quotes returned from Quotable.")

    quotes = []
    for item in data:
        content = (item.get("content") or "").strip()
        author = (item.get("author") or "").strip()

        if not content or not author:
            continue

        quotes.append({
            "text": content,
            "author": author,
        })

    if not quotes:
        raise RuntimeError("No usable quotes returned from Quotable.")

    return quotes


def pick_unsent_quote(quotes: list[dict], sent_quotes: set[str]) -> tuple[dict, str]:
    unsent = []

    for quote in quotes:
        fp = quote_fingerprint(quote["text"], quote["author"])
        if fp not in sent_quotes:
            unsent.append((quote, fp))

    if not unsent:
        raise RuntimeError("All fetched quotes have already been sent. Try again later.")

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
    quotes = fetch_random_quotes(limit=20)
    chosen_quote, fingerprint = pick_unsent_quote(quotes, sent_quotes)

    send_to_discord(webhook_url, chosen_quote)

    sent_quotes.add(fingerprint)
    save_sent_quotes(sent_quotes)


if __name__ == "__main__":
    main()
