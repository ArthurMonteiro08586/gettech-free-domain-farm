#!/usr/bin/env python3
"""
gt_farm.py — mass .tech domain farm for get.tech (Hacktoberfest promo, free 1 year).

One account per domain (coupon is 1 free domain per account). Accounts are created
from fresh throwaway inboxes (voidash API — unlimited, no email verification needed)
or from an optional email:pass pool file (GT_MAILS_FILE env, one "email:password"
per line).

Usage:
    python gt_farm.py [worker_id] [num_workers]      # shard candidates across workers

Output:
    gt_bank.jsonl        — one record per claimed domain:
                           email, gettech_password, customerid, domain, invoiceid,
                           orderid, discount, ts  (THIS IS YOUR DNS ACCESS — back it up)
    gt_farm_state_wN.json — resume state per worker

Optional env:
    GT_MAILS_FILE       — email:pass pool used when voidash inbox creation fails
    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, TELEGRAM_THREAD_ID — success notifications

Edit CANDIDATE SEEDS below to farm your own names.
"""
import json, time, re, random, sys, os, string
from curl_cffi import requests as cr
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

API = "https://get.tech/api"
COUPON = "hacktoberfestd0b8o5"
BANK = os.path.join(os.getcwd(), "gt_bank.jsonl")
MAILS = os.environ.get("GT_MAILS_FILE", "")
WORKER = int(sys.argv[1]) if len(sys.argv) > 1 else 0
NWORKERS = int(sys.argv[2]) if len(sys.argv) > 2 else 1
STATE = os.path.join(os.getcwd(), "gt_farm_state_w%d.json" % WORKER)

# ── CANDIDATE SEEDS ─────────────────────────────────────────────────────────
BRANDS = ["iishko", "alstack", "teleraptor", "gothide", "apodex", "keyfarm",
          "darkharvest", "blastmail", "gothtech", "reformx"]
BASES = ["reform", "goth", "ghost", "phantom", "cyber", "hack", "breach", "proxy",
         "farm", "relay", "orca", "neon", "void", "flux", "nova", "pulse",
         "quantum", "zero", "omega", "delta", "sigma", "titan", "hyper", "meta",
         "ultra", "mega", "shadow", "storm", "blade", "frost", "ember", "venom",
         "rogue", "drift", "echo", "onyx", "raven", "wolf", "viper", "crypt",
         "node", "stack", "forge", "beacon", "harbor", "summit", "vertex",
         "zenith", "matrix", "vector", "cipher", "daemon", "kernel", "socket",
         "packet", "binary", "logic", "syntax", "tensor", "neural", "synth"]
SUFFIX = ["", "hub", "lab", "labs", "dev", "pro", "ai", "net", "zone", "base",
          "core", "works", "ops", "sys", "x", "2026", "hq", "one", "plus", "max"]
CANDIDATES = BRANDS[:]
for b in BASES:
    for sfx in SUFFIX:
        c = b + sfx
        if c not in CANDIDATES:
            CANDIDATES.append(c)
CANDIDATES = [c for i, c in enumerate(CANDIDATES) if i % NWORKERS == WORKER]
# ────────────────────────────────────────────────────────────────────────────

VOIDASH_DOMAINS = ["voidash.bond", "govno.eu.cc", "musor.eu.cc", "pomoi.eu.cc"]


def log(*a):
    print(time.strftime("%H:%M:%S"), "[w%d]" % WORKER, *a, flush=True)


def tg_notify(text):
    tok = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat = os.environ.get("TELEGRAM_CHAT_ID")
    if not tok or not chat:
        return
    try:
        import urllib.request, urllib.parse
        url = "https://api.telegram.org/bot" + tok + "/sendMessage"
        data = {"chat_id": chat, "text": text}
        if os.environ.get("TELEGRAM_THREAD_ID"):
            data["message_thread_id"] = os.environ["TELEGRAM_THREAD_ID"]
        urllib.request.urlopen(urllib.request.Request(
            url, data=urllib.parse.urlencode(data).encode()), timeout=30)
    except Exception as e:
        log("tg EXC:", e)


def load_state():
    try:
        return json.load(open(STATE, encoding="utf-8"))
    except Exception:
        return {"done": [], "mails_idx": 0}


def save_state(st):
    json.dump(st, open(STATE, "w", encoding="utf-8"), indent=1)


def bank_append(rec):
    with open(BANK, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def load_mails():
    out = []
    if not MAILS or not os.path.exists(MAILS):
        return out
    for line in open(MAILS, encoding="utf-8", errors="replace"):
        line = line.strip()
        if line and not line.startswith("#") and ":" in line:
            out.append(line)
    return out


def voidash_email():
    """Fresh unlimited inbox (signup needs NO email verification)."""
    import urllib.request
    dom = random.choice(VOIDASH_DOMAINS)
    try:
        req = urllib.request.Request(
            "https://api.voidash.com/api/v1/inboxes",
            data=json.dumps({"domain": dom}).encode(),
            headers={"Content-Type": "application/json"})
        j = json.loads(urllib.request.urlopen(req, timeout=30).read())
        return j["address"] + ":voidash-no-pass"
    except Exception as e:
        log("voidash EXC:", str(e)[:80])
        return None


def call(s, method, url, tries=5, **kw):
    for i in range(tries):
        try:
            r = s.request(method, url, **kw)
            if r.status_code != 504:
                return r
            time.sleep(12 + i * 8)
        except Exception as e:
            log("  net EXC", str(e)[:80])
            time.sleep(12)
    return None


def new_session(dom_hint="x"):
    for _ in range(6):
        s = cr.Session(impersonate="chrome131")
        r = call(s, "GET",
                 "https://get.tech/search?domain=" + dom_hint + "&coupon=" + COUPON,
                 tries=2, timeout=60)
        if r is not None and r.status_code == 200:
            m = re.search(r'name="csrf-token"\s+content="([^"]+)"', r.text)
            s.headers.update({
                "X-CSRF-TOKEN": m.group(1) if m else "",
                "X-Requested-With": "XMLHttpRequest",
                "Accept": "application/json, text/plain, */*",
                "Referer": "https://get.tech/search", "Origin": "https://get.tech"})
            return s
        time.sleep(20)
    return None


def availability(s, name):
    r = call(s, "GET", API + "/search-availability", params={"domain": name},
             tries=3, timeout=60)
    if r is None:
        return None
    try:
        return r.json()
    except Exception:
        return {"_raw": r.text[:200]}


def gen_password():
    return "Gt!" + "".join(random.choices(string.ascii_letters + string.digits, k=12))


def signup(s, email, pwd):
    payload = {"signup": {
        "name": "John Smith", "address": "12 Main Street", "company": "N/A",
        "city": "Wilmington", "zip": "19801", "username": email.lower(), "password": pwd,
        "countryCode": "1", "phone": "2025550" + str(random.randint(100, 999)),
        "country": "US", "state": "Other", "otherState": "other"}}
    r = call(s, "POST", API + "/signup", json=payload, tries=4, timeout=90)
    if r is None:
        return None, "signup 504"
    try:
        j = r.json()
    except Exception:
        j = {"_raw": r.text[:200]}
    return r.status_code, j


def login(s, email, pwd):
    r = call(s, "POST", API + "/login",
             json={"username": email.lower(), "password": pwd}, tries=4, timeout=110)
    if r is None:
        return None, None
    try:
        return r.status_code, r.json()
    except Exception:
        return r.status_code, None


def claim(s, cust, dom, price):
    item = {"category": "domorder", "product": "dottech", "domain": dom + ".tech",
            "duration": 1, "price": price}
    r = call(s, "POST", API + "/update-cart", json={"cart": [item]}, tries=4, timeout=110)
    if r is None or "updated" not in r.text:
        return {"step": "cart", "err": r.text[:100] if r else "504"}
    r = call(s, "POST", API + "/test-coupon", json={"coupon": COUPON}, tries=4, timeout=170)
    tc = {"code": r.status_code if r else 504, "body": r.text[:200] if r else ""}
    # place-order in up to 3 rounds; between rounds check cart (empty cart = placed)
    cart_txt = "n/a"
    for rnd in range(3):
        r = call(s, "POST", API + "/place-order", tries=4, timeout=170)
        if r is not None and r.status_code == 200:
            try:
                return {"ok": True, "coupon": tc, "order": r.json()}
            except Exception:
                return {"ok": True, "coupon": tc, "order": {"raw": r.text[:500]}}
        rc = call(s, "GET", API + "/get-cart", tries=3, timeout=60)
        cart_txt = rc.text[:200] if rc is not None else "504"
        if rc is not None and '"domorder"' not in rc.text:
            return {"ok": "maybe", "coupon": tc, "cart_after": cart_txt,
                    "note": "cart empty after 504 — order probably placed, verify"}
        if r is not None and r.status_code != 504:
            return {"step": "place-order",
                    "err": str(r.status_code) + " " + r.text[:150], "coupon": tc}
        log("  place-order round", rnd, "504-storm, cart still full, retrying")
        time.sleep(30 + rnd * 30)
    return {"step": "place-order", "err": "504-storm", "cart_after": cart_txt,
            "note": "VERIFY MANUALLY: order may have been placed origin-side",
            "coupon": tc}


def main():
    st = load_state()
    mails = load_mails()
    log("mail pool:", len(mails), "candidates:", len(CANDIDATES))
    claimed = set()
    try:
        for line in open(BANK, encoding="utf-8"):
            claimed.add(json.loads(line)["domain"].split(".")[0])
    except FileNotFoundError:
        pass
    log("already claimed:", sorted(claimed))

    s = new_session()
    if s is None:
        log("origin down, exiting")
        tg_notify("GT farm: origin down at start")
        return
    r = call(s, "GET", API + "/pricing", tries=4, timeout=110)
    if r is None:
        log("pricing down, exiting")
        return
    try:
        pricing = json.loads(r.json()["pricing"])
        price = pricing["dottech"]["addnewdomain"]["1"] * 1
    except Exception as e:
        log("pricing fail:", e)
        return
    log("price 1y:", price)

    for dom in CANDIDATES:
        if dom in st["done"] or dom in claimed:
            continue
        av = availability(s, dom)
        if av is None:
            log(dom, "availability 504, re-sess")
            s = new_session(dom) or s
            av = availability(s, dom)
        exact = None
        if isinstance(av, list):
            for it in av:
                if isinstance(it, dict) and it.get("domain", "").lower() == dom + ".tech":
                    exact = it
                    break
        if exact is None or exact.get("status") != "available" or "pricing" in (exact or {}):
            st["done"].append(dom)
            save_state(st)
            time.sleep(5)
            continue
        log(dom, "AVAILABLE -> claiming")
        # fresh account: try up to 8 mails
        cust = None
        email = None
        gpwd = None
        for _try in range(8):
            cred = voidash_email()
            if cred is None and mails:
                if st["mails_idx"] >= len(mails):
                    log("mails exhausted")
                    break
                cred = mails[st["mails_idx"]]
                st["mails_idx"] += 1
                save_state(st)
            if cred is None:
                time.sleep(20)
                continue
            email, mpwd = cred.split(":", 1)
            gpwd = gen_password()
            code, j = signup(s, email, gpwd)
            cust = j.get("customerid") if isinstance(j, dict) else None
            if cust:
                break
            msg = json.dumps(j)[:120] if j else str(code)
            if "already a Customer" in msg:
                # CF 504'd an earlier signup that ACTUALLY succeeded origin-side:
                # the "fresh" inbox is already ours — login persistently.
                own = any(email.endswith("@" + d) for d in VOIDASH_DOMAINS)
                for lt in range(8 if own else 1):
                    code2, j2 = login(s, email, gpwd)
                    cust = j2.get("customerid") if isinstance(j2, dict) else None
                    if cust:
                        break
                    log("  login retry", lt, "for", email, "->", code2)
                    time.sleep(30 + lt * 15)
                if cust:
                    break
                log("  mail taken:", email, "-> next")
                time.sleep(5)
                continue
            if j is None or code is None:
                log("  signup 504 storm:", email, "-> retry same mail next round")
                time.sleep(30)
                continue
            log("  signup odd:", email, msg, "-> next")
            time.sleep(5)
        if not cust:
            log(dom, "NO ACCOUNT possible, skip")
            st["done"].append(dom + ":noacct")
            save_state(st)
            time.sleep(30)
            continue
        log(dom, "account ok cust", cust, email)
        res = claim(s, cust, dom, price)
        rec = {"email": email, "gettech_password": gpwd, "customerid": cust,
               "domain": dom + ".tech", "ts": time.strftime("%F %T"), "result": res,
               "dns_note": "DNS manage: login get.tech -> My Account -> manage domain DNS/NS"}
        if res.get("ok"):
            try:
                o = json.loads(res["order"]["order"][0])
                rec["invoiceid"] = o.get("invoiceid")
                rec["orderid"] = o.get("orderid")
                rec["discount"] = o.get("discount")
            except Exception:
                pass
            log(dom, "CLAIMED", rec.get("invoiceid"))
            tg_notify("GET.TECH CLAIMED: " + dom + ".tech (free 1y, inv "
                      + str(rec.get("invoiceid")) + ") acct " + email)
            claimed.add(dom)
        else:
            log(dom, "CLAIM FAIL", json.dumps(res)[:250])
        bank_append(rec)
        st["done"].append(dom)
        save_state(st)
        time.sleep(20 + random.randint(0, 20))

    log("FARM COMPLETE. bank:", BANK)
    tg_notify("GET.TECH farm worker %d finished" % WORKER)


if __name__ == "__main__":
    main()
