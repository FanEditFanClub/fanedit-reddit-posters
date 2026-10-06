#!/usr/bin/env python3
"""Post new Reddit items from the daily browser scan; each item goes out
24 hours after its Reddit timestamp.

The 5pm ET browser scan publishes the multireddit listing to GitHub Pages
(Reddit's public RSS died 2026-11-13). This job ticks every 15 minutes and
releases an item once now - published >= 24h. First run baselines (marks
existing items seen, posts nothing). Crossposts/reposts are skipped,
mirroring the old Zapier filter/code step. Returns a report dict; run.py
aggregates and alerts.
"""
from __future__ import annotations

import datetime
import json
import re
import urllib.error
import urllib.request

from common import load_config, load_state, save_state, log
from destinations import (DestinationError, post_buffer_x, post_discord,
                          post_facebook_page, resolve_buffer_profile_id)

DESTS = ("discord", "x", "facebook")

SCAN_UA = "fanedit-reddit-posters/1.0 (by /u/faneditfanclub)"
# Items relay 24h after their Reddit timestamp (the user's spacing rule).
RELAY_DELAY = datetime.timedelta(hours=24)


def fetch_scan_items(scan_url: str) -> list:
    """Read the daily browser-scan JSON from GitHub Pages.

    Returns [{id, title, link, published}] where id is the permalink URL
    (stable, unique) and published is an aware datetime. The scan keeps a
    ~48h lookback so a missed day self-heals.
    """
    req = urllib.request.Request(scan_url, headers={"User-Agent": SCAN_UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = json.load(r)
    items = []
    for p in data.get("posts", []):
        title = (p.get("title") or "").strip()
        link = (p.get("url") or "").strip()
        try:
            published = datetime.datetime.fromisoformat(
                (p.get("published") or "").strip().replace("Z", "+00:00"))
            if published.tzinfo is None:
                published = published.replace(
                    tzinfo=datetime.timezone.utc)
        except (TypeError, ValueError):
            continue
        if title and link:
            items.append({"id": link, "title": title, "link": link,
                          "description": "", "published": published})
    return items


def is_crosspost(item: dict, patterns: list) -> bool:
    """Port of the old Zapier 'Code by Zapier' crosspost check: title+content."""
    text = (item["title"] + " " +
            re.sub(r"<[^>]+>", " ", item["description"])).lower()
    return any(p in text for p in patterns)


def run(cfg: dict, ctx: dict) -> dict:
    report = {"source": "reddit", "new_posts": 0, "errors": [],
              "handoffs": [], "skipped_crossposts": 0}
    scan_url = (cfg.get("reddit") or {}).get("scan_url", "")
    if not scan_url:
        report["errors"].append("reddit scan_url not configured")
        return report
    try:
        items = fetch_scan_items(scan_url)
    except urllib.error.HTTPError as e:
        report["errors"].append(f"reddit scan fetch HTTP {e.code}")
        return report
    except Exception as e:  # noqa: BLE001
        report["errors"].append(f"reddit scan fetch: {e}")
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
    now = datetime.datetime.now(datetime.timezone.utc)
    postable = []
    waiting = 0
    for i in items:
        if i["id"] in seen:
            continue
        if is_crosspost(i, patterns):
            seen.add(i["id"])  # filtered like the old filter step: never posted
            report["skipped_crossposts"] += 1
            continue
        # Relay 24h after the Reddit timestamp; younger items stay unseen
        # and are reconsidered on later ticks.
        if now - i["published"] < RELAY_DELAY:
            waiting += 1
            continue
        postable.append(i)
    if waiting:
        log(f"reddit: {waiting} item(s) seen but younger than 24h, holding.")
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
