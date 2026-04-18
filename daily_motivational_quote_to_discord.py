import hashlib
import json
import os
import random
from pathlib import Path

import requests

ZENQUOTES_RANDOM_URL = "https://zenquotes.io/api/random"
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


def fetch_random_quote() -> dict:
    response = requests.get(ZENQUOTES_RANDOM_URL, timeout=30)
    response.raise_for_status()
    data = response.json()

    if not isinstance(data, list) or not data:
        raise RuntimeError("No quote returned from ZenQuotes.")

    item = data[0]
    text = (item.get("q") or "").strip()
    author = (item.get("a") or "").strip()

    if not text or not author:
        raise RuntimeError("ZenQuotes returned an unusable quote.")

    return {
        "text": text,
        "author": author,
    }


def fetch_unsent_quote(sent_quotes: set[str], max_attempts: int = 20) -> tuple[dict, str]:
    for _ in range(max_attempts):
        quote = fetch_random_quote()
        fp = quote_fingerprint(quote["text"], quote["author"])
        if fp not in sent_quotes:
            return quote, fp

    raise RuntimeError("Could not fetch a new unsent quote after multiple attempts.")


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
    chosen_quote, fingerprint = fetch_unsent_quote(sent_quotes)

    send_to_discord(webhook_url, chosen_quote)

    sent_quotes.add(fingerprint)
    save_sent_quotes(sent_quotes)


if __name__ == "__main__":
    main()
