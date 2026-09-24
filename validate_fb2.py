"""Validate the FACEBOOK_PAGE_TOKEN without ever printing it."""
import json
import os
import urllib.parse
import urllib.request

fb_token = os.environ["FACEBOOK_PAGE_TOKEN"]
url = ("https://graph.facebook.com/v21.0/me?fields=id,name&"
       + urllib.parse.urlencode({"access_token": fb_token}))
try:
    with urllib.request.urlopen(urllib.request.Request(url), timeout=60) as r:
        me = json.load(r)
    print("TOKEN_OK name=", me.get("name"), "id=", me.get("id"))
except Exception as e:
    body = ""
    if hasattr(e, "read"):
        try:
            body = e.read().decode("utf-8", errors="replace")
        except Exception:
            pass
    print("TOKEN_BAD", str(e)[:150], body[:200].replace(fb_token, "***"))
