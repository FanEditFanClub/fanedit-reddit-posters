#!/usr/bin/env python3
"""Poll the Reddit RSS feed; post new items.

First run baselines (marks existing items seen, posts nothing). Retries once
on HTTP 429; a second 429 is surfaced as an error. Crossposts/reposts are
skipped, mirroring the old Zapier filter/code step. Returns a report dict;
run.py aggregates and alerts.
"""
from __future__ import annotations

import re
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

from common import load_config, load_state, save_state, log
from destinations import (DestinationError, post_buffer_x, post_discord,
                          post_facebook_page, resolve_buffer_profile_id)

DESTS = ("discord", "x", "facebook")

# Reddit 403s non-browser user agents; a browser UA gets through.
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")


def _fetch_once(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def fetch_feed(url: str) -> bytes:
    try:
        return _fetch_once(url)
    except urllib.error.HTTPError as e:
        if e.code != 429:
            raise
    except Exception:
        pass  # transient network drop; fall through to the one retry
    log("Reddit fetch failed (429 or dropped connection), retrying once after 60s...")
    time.sleep(60)
    return _fetch_once(url)  # a second failure surfaces as an error


ATOM = "{http://www.w3.org/2005/Atom}"


def parse_items(raw: bytes) -> list:
    root = ET.fromstring(raw)
    items = []
    for e in root.iter(ATOM + "entry"):  # Atom (what Reddit serves)
        title = (e.findtext(ATOM + "title") or "").strip()
        eid = (e.findtext(ATOM + "id") or "").strip()
        link = ""
        for l in e.iter(ATOM + "link"):
            if l.get("rel", "alternate") == "alternate" and l.get("href"):
                link = l.get("href")
                break
        content = e.findtext(ATOM + "content") or ""
        if eid:
            items.append({"id": eid, "title": title, "link": link,
                          "description": content})
    for it in root.iter("item"):  # RSS 2.0 fallback
        title = (it.findtext("title") or "").strip()
        link = (it.findtext("link") or "").strip()
        guid = (it.findtext("guid") or link).strip()
        desc = (it.findtext("description") or "")
        if guid:
            items.append({"id": guid, "title": title, "link": link,
                          "description": desc})
    return items


def is_crosspost(item: dict, patterns: list) -> bool:
    """Port of the old Zapier 'Code by Zapier' crosspost check: title+content."""
    text = (item["title"] + " " +
            re.sub(r"<[^>]+>", " ", item["description"])).lower()
    return any(p in text for p in patterns)


def run(cfg: dict, ctx: dict) -> dict:
    report = {"source": "reddit", "new_posts": 0, "errors": [],
              "handoffs": [], "skipped_crossposts": 0}
    rss_url = (cfg.get("reddit") or {}).get("rss_url", "")
    if not rss_url:
        report["errors"].append("reddit rss_url not configured")
        return report
    try:
        items = parse_items(fetch_feed(rss_url))
    except urllib.error.HTTPError as e:
        if e.code == 429:
            report["errors"].append("reddit 429 persisted after retry")
        else:
            report["errors"].append(f"reddit fetch HTTP {e.code}")
        return report
    except Exception as e:  # noqa: BLE001
        report["errors"].append(f"reddit fetch: {e}")
        return report

    st = load_state("seen_reddit.json", {"seen_ids": [], "baselined": False})
    seen = set(st["seen_ids"])

    if not st.get("baselined"):
        st["seen_ids"] = sorted({i["id"] for i in items})
        st["baselined"] = True
        save_state("seen_reddit.json", st)
        log(f"BASELINE reddit: marked {len(st['seen_ids'])} existing items seen, posted nothing.")
        return report

    patterns = cfg["reddit"].get("crosspost_patterns", [])
    postable = []
    for i in items:
        if i["id"] in seen:
            continue
        if is_crosspost(i, patterns):
            seen.add(i["id"])  # filtered like the old filter step: never posted
            report["skipped_crossposts"] += 1
            continue
        postable.append(i)
    if postable and not ctx.get("buffer_pid"):
        try:
            ctx["buffer_pid"] = resolve_buffer_profile_id(
                ctx["buffer_token"], cfg["buffer"]["channel_name"])
        except DestinationError as e:
            report["errors"].append(f"buffer profile resolve: {e}")

    for i in postable:
        tpl = cfg["templates"]["reddit"]
        texts = {d: tpl[d].format(title=i["title"], url=i["link"])
                 for d in DESTS}
        results: dict = {}
        for d in DESTS:
            try:
                if d == "discord":
                    post_discord(ctx["discord_token"],
                                 ctx["discord_reddit_cid"], texts[d])
                elif d == "x":
                    post_buffer_x(ctx["buffer_token"],
                                  ctx["buffer_pid"], texts[d])
                else:
                    post_facebook_page(ctx["fb_token"], ctx["fb_page_id"],
                                       texts[d], link=i["link"])
                results[d] = True
            except Exception as e:  # noqa: BLE001
                results[d] = f"ERROR: {e}"
        if all(v is True for v in results.values()):
            seen.add(i["id"])
            report["new_posts"] += 1
        else:
            for dest, res in results.items():
                if res is not True:
                    report["errors"].append(f"reddit->{dest}: {res}")

    st["seen_ids"] = sorted(seen)
    save_state("seen_reddit.json", st)
    return report


if __name__ == "__main__":
    print("use run.py as the entrypoint")
