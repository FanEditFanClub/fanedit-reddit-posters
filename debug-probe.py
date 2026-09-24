#!/usr/bin/env python3
"""Focused probe: discordbot UA vs curl UA, spaced out, with rate-limit detail."""
import os
import time
import urllib.request
import urllib.error


def test(name, url, headers):
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=30) as r:
            print(f"{name}: HTTP {r.status}", flush=True)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:200]
        print(f"{name}: HTTP {e.code} body={body}", flush=True)
    except Exception as e:  # noqa: BLE001
        print(f"{name}: ERROR {type(e).__name__}", flush=True)


dt = os.environ.get("DISCORD_BOT_TOKEN", "")
url = "https://discord.com/api/v10/users/@me/guilds"
test("discord ua=discordbot t0", url,
     {"Authorization": "Bot " + dt,
      "User-Agent": "DiscordBot (https://faneditfanclub.local, 1.0)"})
time.sleep(15)
test("discord ua=discordbot t15", url,
     {"Authorization": "Bot " + dt,
      "User-Agent": "DiscordBot (https://faneditfanclub.local, 1.0)"})
time.sleep(15)
test("discord ua=curl t30", url,
     {"Authorization": "Bot " + dt, "User-Agent": "curl/8.9.1"})
