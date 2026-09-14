import json
import re
from pathlib import Path

html_path = Path(r"C:\Users\ZFGJ-WCH\Downloads\Temu.html")
text = html_path.read_text(encoding="utf-8", errors="replace")

# window assignments
for name in [
    "rawData",
    "__NEXT_DATA__",
    "__INITIAL_STATE__",
    "__PageContext__",
    "__DOC_SOURCE__",
    "leoConfig",
]:
    m = re.search(rf"window\.{name}\s*=\s*(\{{)", text)
    if m:
        print(f"found window.{name} at", m.start())

# extract serializeRawData / rawData blob
for pat in [
    r"window\.rawData\s*=\s*(\{.*?\});?\s*</script>",
    r'"rawData"\s*:\s*(\{.*?\})\s*,\s*"',
    r"serializeRawData[^;]*;.*?(\{\\\"store\\\".*?\})",
]:
    m = re.search(pat, text, re.S)
    if m:
        print("pattern match", pat[:40], "len", len(m.group(1)))

# search for goods_list in html
for kw in [
    "goods_list",
    "605773392409873",
    "noResult",
    "No results",
    "search_method",
    "login_scene",
    "isLogin",
    "shield_all",
    "gin_fallback",
    "p_search",
    "store",
    "searchResult",
]:
    print(kw, "count", text.count(kw))

# find script containing search key context
idx = text.find("605773392409873")
if idx >= 0:
    print("\ncontext around search key:")
    print(text[max(0, idx - 200) : idx + 400])

# extract window.__...Store__ or similar large json
scripts = re.findall(r"<script[^>]*>(.*?)</script>", text, re.S)
big = sorted(scripts, key=len, reverse=True)[:5]
for i, s in enumerate(big):
    print(f"\n=== script #{i} len={len(s)} head ===")
    print(s[:500])
    if "goods" in s.lower() or "search" in s.lower():
        for token in ["goods_list", "items", "noResult", "filter", "risk", "login"]:
            if token in s:
                pos = s.find(token)
                print(f"  ...{token}...", s[max(0, pos - 80) : pos + 200])

# HAR phantom a4
har_path = Path(r"C:\Users\ZFGJ-WCH\Downloads\www.temu.com.har")
har = json.loads(har_path.read_text(encoding="utf-8"))
for e in har["log"]["entries"]:
    url = e["request"]["url"]
    if "phantom/xg/pfb/a4" in url:
        print("\n=== phantom a4 ===")
        print("status", e["response"].get("status"), "error", e.get("_error"))
        print("req headers sample:")
        for h in e["request"]["headers"]:
            if h["name"].lower() in ("anti-content", "referer", "cookie", "user-agent"):
                val = h["value"]
                print(" ", h["name"], val[:120] + ("..." if len(val) > 120 else ""))
        body = e.get("response", {}).get("content", {}).get("text") or ""
        print("resp body", body[:300] if body else "(empty)")

# main search page document request
for e in har["log"]["entries"]:
    url = e["request"]["url"]
    if "search_result.html" in url and e["request"]["method"] == "GET":
        print("\n=== search_result.html GET ===")
        print(url[:250])
        print("status", e["response"].get("status"))
        rb = e.get("response", {}).get("content", {}).get("text") or ""
        if rb:
            print("has goods_list", "goods_list" in rb)
            print("has noResultFor", "noResultFor" in rb or "No results" in rb)
            gi = rb.find("goods_list")
            if gi >= 0:
                print(rb[gi : gi + 300])
        break

# all poppy search endpoints
for e in har["log"]["entries"]:
    url = e["request"]["url"]
    if "/api/poppy/" in url and "search" in url:
        print("\n", url.split("?")[0], e["response"].get("status"))
        b = e.get("response", {}).get("content", {}).get("text") or ""
        if b:
            try:
                j = json.loads(b)
                print(json.dumps(j, ensure_ascii=False)[:1500])
            except Exception:
                print(b[:500])

# PMM events of interest
events = []
for e in har["log"]["entries"]:
    post = e.get("request", {}).get("postData") or {}
    t = post.get("text") or ""
    for ev in re.findall(r'"custom_event":"([^"]+)"', t):
        if any(
            x in ev.lower()
            for x in [
                "cart",
                "auth",
                "login",
                "risk",
                "devtool",
                "phantom",
                "search",
                "tz",
                "invalid",
            ]
        ):
            events.append(ev)
from collections import Counter

print("\nPMM interesting events:", Counter(events))
