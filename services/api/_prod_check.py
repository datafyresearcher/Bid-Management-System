import json
import urllib.request

BASE = "https://bms-ahte-api.vercel.app"


def post(path, payload):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=40) as r:
        return json.loads(r.read())


def get(path, token):
    req = urllib.request.Request(BASE + path, headers={"Authorization": "Bearer " + token})
    with urllib.request.urlopen(req, timeout=40) as r:
        return json.loads(r.read())


auth = post("/api/auth/login", {"email": "admin@ahte.local", "password": "admin123"})
d = get("/api/dashboard", auth["token"])

print("PRODUCTION:", BASE)
print("feed_mode:", d["feed_mode"])
print()
print("=== SOURCES (production registry) ===")
for s in d["sources"]:
    print("{:12} tier={:3} records={:2} health={:5} {:18} {}".format(
        s["code"], s["tier"] or "-", s["records"], s["health"], s["access"], s["url"]))
    print("             authority: {}".format(s["authority"]))
    print("             listing  : {}".format(s["listing_url"]))

print()
print("=== PER-RECORD ATTRIBUTION (production) ===")
for g in d["pending_gates"][:5]:
    src = (g.get("opportunity") or {}).get("source")
    if not src:
        print("!! no attribution on gate", g["id"])
        continue
    print("gate G{} | {}".format(g["gate"], (g.get("opportunity") or {}).get("title", "")[:46]))
    print("   {} (tier {})  ref={}".format(src["name"], src["tier"], src["reference"]))
    print("   {}".format(src["notice_url"]))

print()
missing = [o["id"] for o in d["closing_soon"] + d["top_opportunities"] if not o.get("source")]
print("records missing attribution:", missing if missing else "none")
dead = [s["code"] for s in d["sources"] if "epms.gov.pk" in (s["url"] or "")]
print("sources still pointing at the dead epms.gov.pk domain:", dead if dead else "none")
