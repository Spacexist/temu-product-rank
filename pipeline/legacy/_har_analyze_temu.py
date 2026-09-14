import json
import re
from collections import Counter, defaultdict

path = r"C:\Users\ZFGJ-WCH\Downloads\www.temu.com.har"
with open(path, encoding="utf-8") as f:
    har = json.load(f)

entries = har["log"]["entries"]
print("total entries:", len(entries))

patterns = [
    "search",
    "phantom",
    "sigerus",
    "tampa",
    "risk",
    "verify",
    "captcha",
    "sec-",
    "login",
    "uranus",
    "yasuo",
    "oak",
    "pfb",
]

api_responses = []
failed = []
search_bodies = []

for e in entries:
    req = e["request"]
    resp = e.get("response", {})
    url = req["url"]
    status = resp.get("status", 0)
    err = e.get("_error")
    if status >= 400 or err:
        failed.append((status, err, url[:160]))

    if "temu.com/api" in url and any(p in url.lower() for p in patterns):
        content = resp.get("content", {})
        body = content.get("text") or ""
        api_responses.append(
            {
                "url": url.split("?")[0],
                "full_url": url,
                "status": status,
                "method": req["method"],
                "body": body,
            }
        )

    if "/api/" in url and "search" in url.lower():
        body = resp.get("content", {}).get("text") or ""
        search_bodies.append((url, status, body))

print("\n=== FAILED / ERRORS (first 40) ===")
for x in failed[:40]:
    print(x)
print("failed count:", len(failed))

print("\n=== API endpoints (filtered) ===")
by_url = defaultdict(list)
for r in api_responses:
    by_url[r["url"]].append(r)

for url, items in sorted(by_url.items()):
    statuses = Counter(i["status"] for i in items)
    print(f"\n{url}  calls={len(items)} statuses={dict(statuses)}")
    for i in items:
        b = i["body"]
        if not b:
            continue
        low = b.lower()
        if '"success":false' in low.replace(" ", "") or "error_code" in low:
            if '"success":true' not in low[:80] or '"success":false' in low:
                print("  INTERESTING:", b[:600])
                break
    else:
        sample = items[0]["body"]
        if sample:
            print("  sample:", sample[:350])

print("\n=== ALL search API calls ===")
for url, status, body in search_bodies:
    print(url[:200])
    print("status:", status)
    print(body[:1200] if body else "(empty)")
    print("---")

events = Counter()
for e in entries:
    post = e.get("request", {}).get("postData") or {}
    text = (post.get("text") or "") + (e.get("response", {}).get("content", {}).get("text") or "")
    for m in re_find_events(text):
        events[m] += 1

print("\n=== PMM custom_event (top 40) ===")
for ev, cnt in events.most_common(40):
    print(cnt, ev)

# anti-content header presence on search
print("\n=== Requests with login_scene / search_result ===")
for e in entries:
    url = e["request"]["url"]
    if "search_result" in url or "search_key" in url:
        if e["request"]["method"] == "GET" and "search_result.html" in url:
            print("PAGE:", url[:200], "status", e["response"].get("status"))
