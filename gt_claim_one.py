#!/usr/bin/env python3
"""
gt_claim_one.py — claim ONE free .tech domain on get.tech (Hacktoberfest promo).

Verified E2E 2026-10-18: total $0, no card needed.

Usage:
    python gt_claim_one.py <domain-name> [email]

    domain-name : label without .tech (e.g. "myproject")
    email       : optional account email (default: fresh throwaway inbox via voidash API)

Account password is generated and printed at the end — SAVE IT (needed for DNS management).

Flow:
    1. GET /search?domain=X&coupon=CODE      -> session + CSRF token
    2. POST /api/signup                       -> create account (no email verification)
    3. GET  /api/pricing                      -> dottech.addnewdomain["1"] = 12.99
    4. GET  /api/search-availability?domain=X -> exact match must be status=available, no "pricing" key
    5. POST /api/update-cart                  -> item MUST include duration:1 + price:12.99
    6. POST /api/test-coupon                  -> "Coupon applied!" / "One year free .tech domain"
    7. POST /api/place-order                  -> 200 {"order":["<json string>"]} -> invoiceid, discount=12.99
"""
import json, re, random, sys, time, string
import urllib.request
from curl_cffi import requests as cr

API = "https://get.tech/api"
COUPON = "hacktoberfestd0b8o5"          # public Hacktoberfest promo
VOIDASH_DOMAINS = ["voidash.bond", "govno.eu.cc", "musor.eu.cc", "pomoi.eu.cc"]


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def voidash_email():
    """Fresh throwaway inbox (get.tech signup needs NO email verification)."""
    dom = random.choice(VOIDASH_DOMAINS)
    req = urllib.request.Request(
        "https://api.voidash.com/api/v1/inboxes",
        data=json.dumps({"domain": dom}).encode(),
        headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=30).read())["address"]


def call(s, method, url, tries=5, **kw):
    """504-tolerant call. get.tech origin is periodically overloaded; CF returns 504
    while the origin may STILL complete the request — never blind-retry place-order."""
    for i in range(tries):
        try:
            r = s.request(method, url, **kw)
            if r.status_code != 504:
                return r
            log("  504, retry in", 15 + i * 10, "s")
            time.sleep(15 + i * 10)
        except Exception as e:
            log("  net EXC", str(e)[:80])
            time.sleep(15)
    return None


def gen_password():
    return "Gt!" + "".join(random.choices(string.ascii_letters + string.digits, k=12))


def new_session(dom_hint):
    s = cr.Session(impersonate="chrome131")   # plain requests/urllib get CF-challenged
    r = call(s, "GET", "https://get.tech/search?domain=" + dom_hint + "&coupon=" + COUPON,
             tries=3, timeout=60)
    if r is None or r.status_code != 200:
        return None
    m = re.search(r'name="csrf-token"\s+content="([^"]+)"', r.text)
    s.headers.update({
        "X-CSRF-TOKEN": m.group(1) if m else "",
        "X-Requested-With": "XMLHttpRequest",
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://get.tech/search",
        "Origin": "https://get.tech",
    })
    return s


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    dom = sys.argv[1].lower().replace(".tech", "")
    email = sys.argv[2] if len(sys.argv) > 2 else voidash_email()
    pwd = gen_password()
    log("domain:", dom + ".tech", "| account:", email)

    s = new_session(dom)
    if s is None:
        log("origin down (504 storm) — retry later"); sys.exit(2)

    # 1. signup
    payload = {"signup": {
        "name": "John Smith", "address": "12 Main Street", "company": "N/A",
        "city": "Wilmington", "zip": "19801", "username": email, "password": pwd,
        "countryCode": "1", "phone": "2025550" + str(random.randint(100, 999)),
        "country": "US", "state": "Other", "otherState": "other"}}
    r = call(s, "POST", API + "/signup", json=payload, tries=4, timeout=90)
    cust = None
    if r is not None:
        try:
            cust = r.json().get("customerid")
        except Exception:
            pass
        if cust is None:
            log("signup:", r.status_code, r.text[:200])
    if cust is None:
        r = call(s, "POST", API + "/login", json={"username": email, "password": pwd},
                 tries=4, timeout=110)
        if r is not None:
            try:
                cust = r.json().get("customerid")
            except Exception:
                pass
    if cust is None:
        log("no account — abort"); sys.exit(3)
    log("account ok, customerid", cust)

    # 2. pricing (keys are STRINGS: addnewdomain["1"], not [1])
    r = call(s, "GET", API + "/pricing", tries=4, timeout=110)
    if r is None:
        log("pricing 504 — abort"); sys.exit(2)
    pricing = json.loads(r.json()["pricing"])
    price = pricing["dottech"]["addnewdomain"]["1"] * 1   # 12.99
    log("1y price:", price, "(privacy_protection add-on",
        pricing["dottech"]["privacy_protection"], "— do NOT enable)")

    # 3. availability
    r = call(s, "GET", API + "/search-availability", params={"domain": dom}, tries=3, timeout=60)
    av = r.json() if r is not None else None
    exact = None
    for it in (av or []):
        if isinstance(it, dict) and it.get("domain", "").lower() == dom + ".tech":
            exact = it
            break
    if exact is None or exact.get("status") != "available" or "pricing" in exact:
        log("NOT available or premium:", json.dumps(av)[:200]); sys.exit(4)

    # 4. cart — item MUST carry duration+price or test-coupon/place-order die with Laravel 500
    item = {"category": "domorder", "product": "dottech",
            "domain": dom + ".tech", "duration": 1, "price": price}
    r = call(s, "POST", API + "/update-cart", json={"cart": [item]}, tries=4, timeout=110)
    if r is None or "updated" not in r.text:
        log("cart fail:", r.text[:150] if r else "504"); sys.exit(5)

    # 5. coupon (already in session via search URL; test-coupon validates it)
    r = call(s, "POST", API + "/test-coupon", json={"coupon": COUPON}, tries=4, timeout=170)
    log("coupon:", r.status_code if r else 504, (r.text[:120] if r else ""))

    # 6. place-order with cart verification between rounds
    for rnd in range(3):
        r = call(s, "POST", API + "/place-order", tries=4, timeout=170)
        if r is not None and r.status_code == 200:
            body = r.json()
            try:
                o = json.loads(body["order"][0])
            except Exception:
                o = {}
            log("CLAIMED!", dom + ".tech")
            log("invoiceid:", o.get("invoiceid"), "| discount:", o.get("discount"),
                "| status:", o.get("actionstatus"))
            log("ACCOUNT -> email:", email, "| password:", pwd, "| customerid:", cust)
            log("DNS: login get.tech with this account -> My Account -> manage DNS/NS")
            return
        rc = call(s, "GET", API + "/get-cart", tries=3, timeout=60)
        if rc is not None and '"domorder"' not in rc.text:
            log("cart empty after 504 — order probably placed origin-side.")
            log("ACCOUNT -> email:", email, "| password:", pwd, "| customerid:", cust)
            log("Verify in account dashboard.")
            return
        log("place-order round", rnd, "failed (504 storm), retrying")
        time.sleep(30 + rnd * 30)
    log("place-order exhausted. ACCOUNT -> email:", email, "password:", pwd)
    log("Re-run later or use gt_retry.py sweeper.")
    sys.exit(6)


if __name__ == "__main__":
    main()
