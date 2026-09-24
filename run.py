#!/usr/bin/env python3
"""fanedit-social-posters entrypoint (Render cron, every 15 min).

Runs the sheet sync and the reddit sync, then commits the updated state/
back to the GitHub repo (Render cron jobs have an ephemeral filesystem, so
seen-ids must be pushed or every run would re-baseline).

Contract: stays quiet when there is nothing new and no errors. Any error is
posted to the Discord error channel (DISCORD_ERROR_CHANNEL) so it gets seen.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

from common import env, req_env, load_config, load_state, log
from destinations import (DestinationError, post_discord,
                          resolve_discord_channel_id)

VERIFY_DEFAULT = {
    "reddit": {"discord_notified": True, "x_notified": True,
               "facebook_notified": True},
    "sheet": {"discord_notified": False, "x_notified": False,
              "facebook_notified": False},
}


def build_ctx(cfg: dict) -> dict:
    discord_token = req_env("DISCORD_BOT_TOKEN")
    ctx = {
        "verify_default": VERIFY_DEFAULT,
        "discord_token": discord_token,
        "buffer_token": req_env("BUFFER_TOKEN"),
        "fb_token": req_env("FACEBOOK_PAGE_TOKEN"),
        "fb_page_id": env("FACEBOOK_PAGE_ID",
                          cfg["facebook"]["page_id"]),
        "buffer_pid": "",
    }
    d = cfg["discord"]
    ctx["discord_sheet_cid"] = resolve_discord_channel_id(
        discord_token, env("DISCORD_SHEET_CHANNEL", d["sheet_channel"]))
    ctx["discord_reddit_cid"] = resolve_discord_channel_id(
        discord_token, env("DISCORD_REDDIT_CHANNEL", d["reddit_channel"]))
    return ctx


def alert(ctx: dict, text: str) -> None:
    """Surface an error where the user will see it: the Discord error channel."""
    channel = env("DISCORD_ERROR_CHANNEL")
    if not channel:
        log("ERROR (no DISCORD_ERROR_CHANNEL set): " + text)
        return
    try:
        cid = resolve_discord_channel_id(ctx["discord_token"], channel)
        post_discord(ctx["discord_token"], cid,
                     f":warning: fanedit-social-posters error\n{text[:1500]}")
    except Exception as e:  # noqa: BLE001
        log(f"ERROR alert failed ({e}): {text}")


def push_state(job: str) -> None:
    """Commit state/ back to GitHub so the next ephemeral run keeps history."""
    pat = env("GITHUB_PAT")
    repo = env("GITHUB_REPO")  # e.g. "octocat/fanedit-social-posters"
    branch = env("GITHUB_BRANCH", "main")
    if not pat or not repo:
        log("GITHUB_PAT/GITHUB_REPO not set; state will not persist "
            "between runs (each run would re-baseline).")
        return
    base = os.path.dirname(os.path.abspath(__file__))
    authed = f"https://x-access-token:{pat}@github.com/{repo}.git"
    cmds = [
        ["git", "config", "user.email", "posters@faneditfanclub.local"],
        ["git", "config", "user.name", "fanedit-social-posters"],
        ["git", "add", "state"],
        ["git", "commit", "-m", f"poster state update ({job})",
         "--allow-empty"],
        # The sibling job may have pushed since this run started; rebase first.
        ["git", "pull", "--rebase", authed, branch],
        ["git", "push", authed, f"HEAD:{branch}"],
    ]
    for c in cmds:
        r = subprocess.run(c, cwd=base, capture_output=True, text=True,
                           timeout=90)
        if r.returncode != 0 and "nothing to commit" not in (
                r.stdout + r.stderr):
            # push failing shouldn't fail the whole run; log loudly instead
            log(f"git state push issue ({' '.join(c[:3])}): "
                f"{(r.stdout + r.stderr)[:300]}")
            if c[1] in ("pull", "push"):
                return
    log("state pushed to GitHub")


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] not in ("reddit", "sheet"):
        print("usage: run.py [reddit|sheet]", flush=True)
        return 2
    job = sys.argv[1]
    cfg = load_config()
    try:
        ctx = build_ctx(cfg)
    except Exception as e:  # noqa: BLE001
        log(f"FATAL building context: {e}")
        return 1

    if job == "sheet":
        import sync_sheet as mod
    else:
        import sync_reddit as mod
    try:
        report = mod.run(cfg, ctx)
    except Exception as e:  # noqa: BLE001
        report = {"source": mod.__name__, "new_posts": 0,
                  "errors": [f"unhandled: {e}"], "handoffs": []}

    push_state(job)

    errors = report.get("errors", [])
    new_posts = report.get("new_posts", 0)
    handoffs = report.get("handoffs", [])
    summary = {"job": job, "report": report, "new_posts": new_posts,
               "errors": errors, "handoffs": handoffs}
    print("REPORT:" + json.dumps(summary), flush=True)

    if errors:
        alert(ctx, "\n".join(f"- {e}" for e in errors))
    if handoffs:
        # First live posts per destination: flag for manual verification.
        alert(ctx, "First live posts went out, please verify manually: "
                   + ", ".join(handoffs))
    if not errors and new_posts == 0:
        log("quiet: nothing new, no errors")
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
