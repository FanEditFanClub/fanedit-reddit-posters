#!/usr/bin/env python3
import os, urllib.request, urllib.error
def test(name, url, headers):
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=30) as r:
            print(f"{name}: HTTP {r.status}", flush=True)
    except urllib.error.HTTPError as e:
        print(f"{name}: HTTP {e.code}", flush=True)
    except Exception as e:
        print(f"{name}: ERROR {type(e).__name__}", flush=True)
bt = os.environ.get("BUFFER_TOKEN", "")
test("buffer-v1-bufferapp-host", "https://api.bufferapp.com/1/user.json?access_token=" + bt, {"User-Agent": "probe/1.0"})
test("buffer-v1-buffer-host", "https://api.buffer.com/1/user.json?access_token=" + bt, {"User-Agent": "probe/1.0"})
test("buffer-v2-bufferapp-host", "https://api.bufferapp.com/2/user.json?access_token=" + bt, {"User-Agent": "probe/1.0"})
