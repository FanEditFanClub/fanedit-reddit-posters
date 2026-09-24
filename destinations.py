"""Post to Discord / Buffer (X) / Facebook Page using env-var tokens.

Secrets (set as env vars on Render):
  DISCORD_BOT_TOKEN  -> Discord bot token (Authorization: Bot <token>)
  BUFFER_TOKEN       -> Buffer API key from publish.buffer.com/settings/api
                        (new public GraphQL API, Authorization: Bearer <token>)
  FACEBOOK_PAGE_TOKEN -> Facebook Page access token

Discord channel ids are resolved at runtime from channel names and cached in
state/discord_channels.json. Buffer channel ids are cached in
state/buffer_profile.json.
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from common import STATE_DIR, log

DISCORD_API = "https://discord.com/api"
# Discord's Cloudflare front door 403s Python-urllib's default UA from
# datacenter IPs; the documented bot UA passes fine.
DISCORD_UA = "DiscordBot (https://faneditfanclub.local, 1.0)"


class DestinationError(RuntimeError):
    pass


def _request(req: urllib.request.Request, label: str) -> dict | list:
    """Open a request, retrying once on 429 honoring Retry-After."""
    for attempt in (1, 2):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                raw = r.read().decode("utf-8", errors="replace")
                if r.status not in (200, 201, 204):
                    raise DestinationError(
                        f"{label} HTTP {r.status}: {raw[:200]}")
                stripped = raw.strip()
                return json.loads(stripped) if stripped else {}
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt == 1:
                retry = e.headers.get("Retry-After")
                try:
                    wait = float(retry) + 1 if retry else 5
                except (TypeError, ValueError):
                    wait = 5
                wait = min(wait, 90)  # never stall a run on a huge retry-after
                log(f"{label} rate-limited; waiting {wait:.0f}s")
                time.sleep(wait)
                continue
            raise DestinationError(
                f"{label} HTTP {e.code}: "
                f"{e.read()[:200].decode(errors='replace')}")
    raise DestinationError(f"{label}: retry exhausted")  # unreachable


def _post(url: str, body: bytes, headers: dict, label: str) -> dict:
    return _request(urllib.request.Request(url, data=body, headers=headers,
                                          method="POST"), label)


def _get(url: str, headers: dict, label: str) -> dict | list:
    return _request(urllib.request.Request(url, headers=headers, method="GET"),
                    label)


def _discord_headers(token: str) -> dict:
    return {"Authorization": f"Bot {token}",
            "Content-Type": "application/json",
            "User-Agent": DISCORD_UA}


def _channel_key(n: str) -> str:
    """Normalize a channel name for matching: strip # and leading emoji."""
    return re.sub(r"^[^a-z0-9]+", "", n.lstrip("#").lower())


def resolve_discord_channel_id(token: str, channel_name: str) -> str:
    """Resolve a channel id from its name, caching it in state."""
    want = _channel_key(channel_name)
    cache = os.path.join(STATE_DIR, "discord_channels.json")
    if os.path.exists(cache):
        with open(cache) as f:
            cid = json.load(f).get(want, "")
        if cid:
            return cid
    headers = _discord_headers(token)
    seen: list = []
    try:
        guilds = _get(f"{DISCORD_API}/users/@me/guilds", headers,
                      "discord guilds")
    except DestinationError as e:
        raise DestinationError(f"discord auth failed (bad token?): {e}")
    for g in guilds if isinstance(guilds, list) else []:
        gid = g.get("id", "")
        try:
            channels = _get(f"{DISCORD_API}/guilds/{gid}/channels", headers,
                            "discord channels")
        except DestinationError:
            continue
        for c in channels if isinstance(channels, list) else []:
            name = str(c.get("name", ""))
            seen.append(f"{g.get('name', '?')}/#{name}")
            if _channel_key(name) == want and c.get("type") == 0:
                os.makedirs(STATE_DIR, exist_ok=True)
                cached = json.load(open(cache)) if os.path.exists(cache) else {}
                cached[want] = c["id"]
                with open(cache, "w") as f:
                    json.dump(cached, f)
                log(f"discord: resolved #{want} -> {c['id']}")
                return c["id"]
    raise DestinationError(
        f"discord: no text channel named #{want} visible to the bot. "
        f"Seen: {', '.join(seen[:20]) or 'nothing'}")


def post_discord(token: str, channel_id: str, text: str) -> bool:
    # Bot posts under its own name/avatar (set in the Discord Developer Portal).
    body = json.dumps({"content": text[:2000]}).encode()
    _post(f"{DISCORD_API}/channels/{channel_id}/messages",
          body, _discord_headers(token), "discord")
    return True


BUFFER_GQL = "https://api.buffer.com"
BUFFER_UA = "poster-pipeline/1.0"


def _buffer_gql(token: str, query: str, variables: dict | None,
                label: str) -> dict:
    """POST a GraphQL operation to Buffer's public API.

    The API answers HTTP 200 for nearly everything, including failures, so
    the GraphQL `errors` array is checked explicitly. Retries once on 429
    honoring Retry-After.
    """
    body = json.dumps({"query": query, "variables": variables or {}}).encode()
    for attempt in (1, 2):
        req = urllib.request.Request(
            BUFFER_GQL, data=body, method="POST",
            headers={"Authorization": f"Bearer {token}",
                     "Content-Type": "application/json",
                     "User-Agent": BUFFER_UA})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                data = json.loads(r.read().decode("utf-8", errors="replace"))
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt == 1:
                retry = e.headers.get("Retry-After")
                try:
                    wait = float(retry) + 1 if retry else 5
                except (TypeError, ValueError):
                    wait = 5
                wait = min(wait, 90)
                log(f"{label} rate-limited; waiting {wait:.0f}s")
                time.sleep(wait)
                continue
            raise DestinationError(
                f"{label} HTTP {e.code}: "
                f"{e.read()[:200].decode(errors='replace')}")
        if not isinstance(data, dict):
            raise DestinationError(f"{label}: unexpected response")
        errs = data.get("errors")
        if errs:
            first = errs[0]
            msg = (first.get("message", str(first))
                   if isinstance(first, dict) else str(first))
            raise DestinationError(f"{label} GraphQL error: {msg[:200]}")
        inner = data.get("data")
        if not isinstance(inner, dict):
            raise DestinationError(f"{label}: empty data in response")
        return inner
    raise DestinationError(f"{label}: retry exhausted")  # unreachable


def resolve_buffer_profile_id(token: str, channel_name: str) -> str:
    """Resolve the Buffer channel id for the X channel via the GraphQL API,
    caching it in state."""
    cache = os.path.join(STATE_DIR, "buffer_profile.json")
    if os.path.exists(cache):
        with open(cache) as f:
            pid = json.load(f).get("profile_id", "")
        if pid:
            return pid
    data = _buffer_gql(
        token, "query { account { organizations { id name } } }",
        None, "buffer account")
    orgs = (data.get("account") or {}).get("organizations") or []
    if not orgs:
        raise DestinationError("buffer: no organizations on this token")
    want = channel_name.lower().replace(" ", "")
    twitter = []
    for org in orgs:
        ch = _buffer_gql(
            token,
            "query($orgId: OrganizationId!) { channels(input: "
            "{organizationId: $orgId}) { id name service } }",
            {"orgId": org["id"]}, "buffer channels")
        for c in ch.get("channels") or []:
            if str(c.get("service", "")).lower() == "twitter":
                twitter.append(c)
    if not twitter:
        raise DestinationError(
            "buffer: no Twitter/X channel found on the token")
    pid = ""
    for c in twitter:
        name = str(c.get("name", "")).lower().replace(" ", "")
        if want and (want in name or name in want):
            pid = c["id"]
            break
    if not pid:
        pid = twitter[0]["id"]
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(cache, "w") as f:
        json.dump({"profile_id": pid, "channel_name": channel_name}, f)
    log(f"buffer: resolved channel {pid}")
    return pid


def post_buffer_x(token: str, profile_id: str, text: str) -> bool:
    data = _buffer_gql(
        token,
        "mutation($input: CreatePostInput!) { createPost(input: $input) "
        "{ __typename ... on PostActionSuccess { post { id status } } } }",
        {"input": {"channelId": profile_id, "text": text,
                   "mode": "shareNow", "schedulingType": "automatic",
                   "needsApproval": False, "assets": []}},
        "buffer createPost")
    payload = data.get("createPost") or {}
    post = payload.get("post") or {}
    log(f"buffer: posted {post.get('id')} status={post.get('status')}")
    return True


def post_facebook_page(token: str, page_id: str, text: str,
                       link: str = "") -> bool:
    params = {"message": text, "access_token": token}
    if link:
        params["link"] = link
    body = urllib.parse.urlencode(params).encode()
    resp = _post(f"https://graph.facebook.com/v21.0/{page_id}/feed", body, {
        "Content-Type": "application/x-www-form-urlencoded",
    }, "facebook")
    if "id" not in resp:
        raise DestinationError(
            f"facebook returned no post id: {str(resp)[:200]}")
    return True
