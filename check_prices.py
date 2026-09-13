"""
Daily price + history checker for a personal wishlist of product URLs.

For each URL in urls.txt:
  - fetches the current price and a product image (Shopify JSON endpoint
    when available, otherwise JSON-LD / meta tags / a regex fallback)
  - appends today's price to that item's rolling 90-day history in prices.json
  - emails a summary if any tracked item's price has dropped

Designed to run once a day via GitHub Actions (see .github/workflows/price-check.yml),
but also runs fine locally: `python check_prices.py`

prices.json feeds index.html, the visual dashboard.
"""

import json
import os
import random
import re
import smtplib
import ssl
import time
from datetime import datetime, timezone
from email.mime.text import MIMEText
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

# Domains known to run Shopify — we can hit their /products/<handle>.json
# endpoint directly instead of scraping HTML, which is faster and more reliable.
SHOPIFY_DOMAINS = {
    "unique-vintage.com",
    "hellbunny.com",
    "vampirefreaks.com",
    "foxblood.com",
    "midnighthour.com",
    "lafemmeennoir.net",
    "livelyghosts.com",
    "shopmyviolet.com",
    "forestinkclothing.com",
}

BASE_DIR = Path(__file__).resolve().parent
URLS_FILE = BASE_DIR / "urls.txt"
PRICES_FILE = BASE_DIR / "prices.json"
TIMEOUT = 20
HISTORY_DAYS = 90


def load_urls():
    urls = []
    seen = set()
    for raw_line in URLS_FILE.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line not in seen:
            seen.add(line)
            urls.append(line)
    return urls


def load_prices():
    if PRICES_FILE.exists():
        return json.loads(PRICES_FILE.read_text())
    return {}


def save_prices(data):
    PRICES_FILE.write_text(json.dumps(data, indent=2, sort_keys=True))


def domain_of(url):
    return urlparse(url).netloc.replace("www.", "")


def try_jsonld(soup):
    """Look for schema.org Product/offers price + image in a <script type="application/ld+json"> block."""
    for tag in soup.find_all("script", {"type": "application/ld+json"}):
        try:
            data = json.loads(tag.string or "{}")
        except (json.JSONDecodeError, TypeError):
            continue
        candidates = data if isinstance(data, list) else [data]
        for item in candidates:
            if not isinstance(item, dict):
                continue
            if "Product" in str(item.get("@type", "")):
                offers = item.get("offers")
                if isinstance(offers, list):
                    offers = offers[0] if offers else None
                if isinstance(offers, dict) and offers.get("price"):
                    try:
                        price = float(str(offers["price"]).replace(",", ""))
                    except ValueError:
                        continue
                    image = item.get("image")
                    if isinstance(image, list):
                        image = image[0] if image else None
                    if isinstance(image, dict):
                        image = image.get("url")
                    return price, item.get("name"), image
    return None, None, None


def try_meta_tags(soup):
    price = None
    for attrs in (
        {"property": "product:price:amount"},
        {"property": "og:price:amount"},
        {"itemprop": "price"},
    ):
        tag = soup.find("meta", attrs=attrs)
        if tag and tag.get("content"):
            try:
                price = float(tag["content"].replace(",", ""))
                break
            except ValueError:
                continue

    image = None
    og_image = soup.find("meta", attrs={"property": "og:image"})
    if og_image and og_image.get("content"):
        image = og_image["content"]

    return price, None, image


def try_regex(html):
    match = re.search(r"\$\s?(\d{1,4}(?:\.\d{2}))", html)
    if match:
        return float(match.group(1)), None, None
    return None, None, None


def try_shopify_json(url):
    parsed = urlparse(url)
    if "/products/" not in parsed.path:
        return None, None, None

    handle = parsed.path.split("/products/", 1)[1].split("/", 1)[0]
    json_url = f"{parsed.scheme}://{parsed.netloc}/products/{handle}.json"

    try:
        resp = requests.get(json_url, headers=HEADERS, timeout=TIMEOUT)
        resp.raise_for_status()
        product = resp.json().get("product", {})
    except Exception:
        return None, None, None

    variants = product.get("variants", [])
    if not variants:
        return None, None, None

    wanted_variant_id = None
    qs = parse_qs(parsed.query)
    if "variant" in qs:
        try:
            wanted_variant_id = int(qs["variant"][0])
        except ValueError:
            pass

    chosen = None
    if wanted_variant_id:
        chosen = next((v for v in variants if str(v.get("id")) == str(wanted_variant_id)), None)
        if chosen is None:
            return None, None, None
    if not chosen:
        chosen = variants[0]

    try:
        price = float(str(chosen["price"]).replace(",", ""))
    except (KeyError, TypeError, ValueError):
        return None, None, None

    image = None
    variant_image = chosen.get("featured_image")
    if isinstance(variant_image, dict) and variant_image.get("src"):
        image = variant_image["src"]
    elif product.get("images"):
        image = product["images"][0].get("src")

    return price, product.get("title"), image


def get_price_and_image(url):
    domain = domain_of(url)

    if domain in SHOPIFY_DOMAINS:
        price, name, image = try_shopify_json(url)
        if price is not None:
            return price, name, image

    try:
        resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        resp.raise_for_status()
    except Exception:
        return None, None, None

    soup = BeautifulSoup(resp.text, "lxml")

    price, name, image = try_jsonld(soup)
    if price is not None:
        if not image:
            _, _, meta_image = try_meta_tags(soup)
            image = meta_image
        return price, name, image

    price, name, image = try_meta_tags(soup)
    if price is not None:
        return price, name, image

    price, name, _ = try_regex(resp.text)
    return price, name, image


def send_email(subject, body):
    gmail_address = os.environ["GMAIL_ADDRESS"]
    gmail_password = os.environ["GMAIL_APP_PASSWORD"]
    notify_to = os.environ.get("NOTIFY_EMAIL", gmail_address)

    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = gmail_address
    msg["To"] = notify_to

    context = ssl.create_default_context()
    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        server.starttls(context=context)
        server.login(gmail_address, gmail_password)
        server.sendmail(gmail_address, [notify_to], msg.as_string())


def main():
    urls = load_urls()
    prices = load_prices()

    drops = []
    failures = []
    now = datetime.now(timezone.utc)
    today_str = now.date().isoformat()

    for url in urls:
        time.sleep(random.uniform(1.5, 3.5))  # spread out requests, don't hammer sites
        price, name, image = get_price_and_image(url)
        record = prices.get(url, {})

        if price is None:
            failures.append(url)
            record["last_checked"] = now.isoformat()
            record["last_error"] = "could not parse a price from this page"
            prices[url] = record
            continue

        previous_price = record.get("price")
        if previous_price is not None and price < previous_price:
            record["pending_alert"] = {
                "url": url,
                "name": name or record.get("name") or url,
                "old_price": previous_price,
                "new_price": price,
            }

        history = record.get("history", [])
        if not history or history[-1]["date"] != today_str:
            history.append({"date": today_str, "price": price})
        else:
            history[-1]["price"] = price  # re-run same day: overwrite, don't duplicate
        history = history[-HISTORY_DAYS:]

        record["price"] = price
        record["history"] = history
        if name:
            record["name"] = name
        if image:
            record["image"] = image
        record["last_checked"] = now.isoformat()
        record.pop("last_error", None)
        prices[url] = record

    drops = [record["pending_alert"] for record in prices.values()
             if "pending_alert" in record]
    save_prices(prices)

    if drops:
        lines = [
            f"{d['name']}\n  ${d['old_price']:.2f} -> ${d['new_price']:.2f}\n  {d['url']}\n"
            for d in drops
        ]
        body = "Price drops found:\n\n" + "\n".join(lines)
        if failures:
            body += f"\n\n({len(failures)} URL(s) couldn't be checked this run.)"
        if os.environ.get("GMAIL_ADDRESS") and os.environ.get("GMAIL_APP_PASSWORD"):
            send_email(f"Price drop(s) found on {len(drops)} item(s)", body)
            for record in prices.values():
                record.pop("pending_alert", None)
            save_prices(prices)
            print(f"Sent alert for {len(drops)} drop(s).")
        else:
            print(f"Found {len(drops)} drop(s); email credentials are not configured.")
    else:
        print("No price drops today.")

    if failures:
        print(f"{len(failures)} URL(s) failed to parse — see prices.json for details:")
        for f in failures:
            print(f"  - {f}")


if __name__ == "__main__":
    main()
