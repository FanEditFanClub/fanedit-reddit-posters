#!/usr/bin/env python3
"""One-off probe: which APIs are reachable from GitHub Actions runners.
Prints ONLY http status codes, never bodies or tokens."""
import os
import urllib.request
import urllib.error


def test(name, url, headers):
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=30) as r:
            print(f"{name}: HTTP {r.status}", flush=True)
    except urllib.error.HTTPError as e:
        print(f"{name}: HTTP {e.code}", flush=True)
    except Exception as e:  # noqa: BLE001
        print(f"{name}: ERROR {type(e).__name__}", flush=True)


dt = os.environ.get("DISCORD_BOT_TOKEN", "")
bt = os.environ.get("BUFFER_TOKEN", "")
fb = os.environ.get("FACEBOOK_PAGE_TOKEN", "")

UAS = {
    "urllib": "Python-urllib/3.12",
    "curl": "curl/8.9.1",
    "browser": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"),
    "discordbot": "DiscordBot (https://faneditfanclub.local, 1.0)",
}
for ua_name, ua in UAS.items():
    test(f"discord-users/@me/guilds ua={ua_name}",
         "https://discord.com/api/v10/users/@me/guilds",
         {"Authorization": "Bot " + dt, "User-Agent": ua})

test("buffer-user", "https://api.buffer.com/1/user.json?access_token=" + bt,
     {"User-Agent": "probe/1.0"})
test("facebook-me", "https://graph.facebook.com/v19.0/me?fields=id,name&access_token=" + fb,
     {"User-Agent": "probe/1.0"})
