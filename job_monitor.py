#!/usr/bin/env python3
"""
Monitor configured job pages for keyword-matching postings and notify Discord.

The monitor is intentionally dependency-free so it can run anywhere Python 3 is
available. Configure websites, keywords, and your Discord webhook in config.json.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen


DEFAULT_CONFIG = Path("config.json")
DEFAULT_SEEN = Path("seen_jobs.json")
USER_AGENT = "JobPostingMonitor/1.0 (+local script)"


@dataclass(frozen=True)
class SiteConfig:
    name: str
    url: str
    include_patterns: list[str]
    exclude_patterns: list[str]


@dataclass(frozen=True)
class Match:
    site_name: str
    title: str
    url: str
    matched_keywords: list[str]


class LinkParser(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.links: list[dict[str, str]] = []
        self._current_href: str | None = None
        self._current_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        attrs_dict = dict(attrs)
        href = attrs_dict.get("href")
        if href:
            self._current_href = urljoin(self.base_url, href)
            self._current_text = []

    def handle_data(self, data: str) -> None:
        if self._current_href:
            self._current_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "a" or not self._current_href:
            return
        text = clean_text(" ".join(self._current_text))
        if text:
            self.links.append({"title": text, "url": self._current_href})
        self._current_href = None
        self._current_text = []


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(value)).strip()


def load_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(
            f"Missing {path}. Copy config.example.json to {path} and edit it."
        )
    with path.open("r", encoding="utf-8") as file:
        config = json.load(file)
    validate_config(config)
    return config


def validate_config(config: dict[str, Any]) -> None:
    required = ["discord_webhook_url", "keywords", "sites"]
    missing = [key for key in required if key not in config]
    if missing:
        raise ValueError(f"Missing required config keys: {', '.join(missing)}")
    if not isinstance(config["keywords"], list) or not config["keywords"]:
        raise ValueError("config.keywords must be a non-empty list")
    if not isinstance(config["sites"], list) or not config["sites"]:
        raise ValueError("config.sites must be a non-empty list")


def build_sites(config: dict[str, Any]) -> list[SiteConfig]:
    sites = []
    for site in config["sites"]:
        name = site.get("name") or site.get("url")
        url = site["url"]
        sites.append(
            SiteConfig(
                name=name,
                url=url,
                include_patterns=site.get("include_url_patterns", []),
                exclude_patterns=site.get("exclude_url_patterns", []),
            )
        )
    return sites


def load_seen(path: Path) -> set[str]:
    if not path.exists():
        return set()
    with path.open("r", encoding="utf-8") as file:
        data = json.load(file)
    return set(data.get("seen_ids", []))


def save_seen(path: Path, seen: set[str]) -> None:
    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "seen_ids": sorted(seen),
    }
    with path.open("w", encoding="utf-8") as file:
        json.dump(payload, file, indent=2)
        file.write("\n")


def fetch_html(url: str, timeout: int) -> str:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=timeout) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


def extract_links(site: SiteConfig, html_text: str) -> list[dict[str, str]]:
    parser = LinkParser(site.url)
    parser.feed(html_text)

    unique: dict[str, dict[str, str]] = {}
    for link in parser.links:
        url = normalize_url(link["url"])
        if not should_keep_url(url, site):
            continue
        unique[url] = {"title": link["title"], "url": url}
    return list(unique.values())


def normalize_url(url: str) -> str:
    parsed = urlparse(url)
    return parsed._replace(fragment="").geturl()


def should_keep_url(url: str, site: SiteConfig) -> bool:
    if site.include_patterns and not any(
        re.search(pattern, url, re.IGNORECASE) for pattern in site.include_patterns
    ):
        return False
    if any(re.search(pattern, url, re.IGNORECASE) for pattern in site.exclude_patterns):
        return False
    return True


def find_matches(
    site: SiteConfig, links: list[dict[str, str]], keywords: list[str]
) -> list[Match]:
    matches = []
    for link in links:
        haystack = f"{link['title']} {link['url']}"
        matched_keywords = [
            keyword for keyword in keywords if re.search(keyword, haystack, re.IGNORECASE)
        ]
        if matched_keywords:
            matches.append(
                Match(
                    site_name=site.name,
                    title=link["title"],
                    url=link["url"],
                    matched_keywords=matched_keywords,
                )
            )
    return matches


def match_id(match: Match) -> str:
    digest = hashlib.sha256(match.url.encode("utf-8")).hexdigest()
    return digest[:24]


def post_discord(webhook_url: str, match: Match, dry_run: bool) -> None:
    content = (
        f"New job posting match on **{match.site_name}**\n"
        f"**{match.title}**\n"
        f"{match.url}\n"
        f"Matched: {', '.join(match.matched_keywords)}"
    )
    if dry_run:
        logging.info("[dry-run] Discord notification:\n%s", content)
        return

    payload = json.dumps({"content": content}).encode("utf-8")
    request = Request(
        webhook_url,
        data=payload,
        headers={"Content-Type": "application/json", "User-Agent": USER_AGENT},
        method="POST",
    )
    with urlopen(request, timeout=20) as response:
        if response.status >= 400:
            raise RuntimeError(f"Discord webhook returned HTTP {response.status}")


def check_once(config: dict[str, Any], seen_path: Path, dry_run: bool) -> int:
    keywords = [str(keyword) for keyword in config["keywords"]]
    sites = build_sites(config)
    timeout = int(config.get("request_timeout_seconds", 20))
    webhook_url = config["discord_webhook_url"]
    seen = load_seen(seen_path)
    new_matches = 0

    for site in sites:
        try:
            logging.info("Checking %s (%s)", site.name, site.url)
            html_text = fetch_html(site.url, timeout)
            links = extract_links(site, html_text)
            matches = find_matches(site, links, keywords)
        except (HTTPError, URLError, TimeoutError, ValueError) as error:
            logging.warning("Could not check %s: %s", site.name, error)
            continue

        for match in matches:
            seen_key = match_id(match)
            if seen_key in seen:
                continue
            post_discord(webhook_url, match, dry_run)
            if not dry_run:
                seen.add(seen_key)
            new_matches += 1

    if not dry_run:
        save_seen(seen_path, seen)
    logging.info("Found %s new match(es)", new_matches)
    return new_matches


def run_forever(config_path: Path, seen_path: Path, dry_run: bool) -> None:
    while True:
        config = load_config(config_path)
        interval = int(config.get("check_interval_seconds", 1800))
        check_once(config, seen_path, dry_run)
        logging.info("Sleeping for %s seconds", interval)
        time.sleep(interval)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Monitor job websites for keywords.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--seen", type=Path, default=DEFAULT_SEEN)
    parser.add_argument("--once", action="store_true", help="Check once and exit.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Log Discord messages instead of sending them.",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(message)s",
    )
    config = load_config(args.config)
    if args.once:
        check_once(config, args.seen, args.dry_run)
        return
    run_forever(args.config, args.seen, args.dry_run)


if __name__ == "__main__":
    main()
