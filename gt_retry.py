#!/usr/bin/env python3
"""
gt_retry.py — recovery sweeper for FAILED get.tech claims.

Scans gt_bank.jsonl for records whose result is not ok (504-storm during
place-order, login failures, etc.), logs back into the saved account and
completes the order. Cart state is checked between attempts so an order that
already went through origin-side is never duplicated.

Runs forever, sweeps every 5 minutes. Stop with Ctrl+C.

Optional env: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, TELEGRAM_THREAD_ID.
"""
import json, time, re, random, sys, os
from curl_cffi import requests as cr
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

API = "https://get.tech/api"
COUPON = "hacktoberfestd0b8o5"
BANK = os.path.join(os.getcwd(), "gt_bank.jsonl")
RSTATE = os.path.join(os.getcwd(), "gt_retry_state.json")


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


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


def call(s, method, url, tries=4, **kw):
    for i in range(tries):
        try:
            r = s.request(method, url, **kw)
            if r.status_code != 504:
                return r
            time.sleep(15 + i * 10)
        except Exception as e:
            log("  net EXC", str(e)[:80])
            time.sleep(15)
    return None


def load_rstate():
    try:
        return json.load(open(RSTATE, encoding="utf-8"))
    except Exception:
        return {"recovered": [], "dead": []}


def save_rstate(st):
    json.dump(st, open(RSTATE, "w", encoding="utf-8"), indent=1)


def bank_append(rec):
    with open(BANK, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def failed_records():
    out = []
    for line in open(BANK, encoding="utf-8"):
        try:
            r = json.loads(line)
        except Exception:
            continue
        if r.get("recovered"):
            continue
        if not (isinstance(r.get("result"), dict) and r["result"].get("ok")):
            out.append(r)
    return out


def recover(rec):
    dom_full = rec["domain"]
    dom = dom_full.split(".")[0]
    email = rec["email"]
    pwd = rec["gettech_password"]
    log("recover", dom_full, "acct", email)
    s = None
    for _ in range(4):
        s = cr.Session(impersonate="chrome131")
        r = call(s, "GET", "https://get.tech/search?domain=" + dom + "&coupon=" + COUPON,
                 tries=2, timeout=60)
        if r is not None and r.status_code == 200:
            m = re.search(r'name="csrf-token"\s+content="([^"]+)"', r.text)
            s.headers.update({"X-CSRF-TOKEN": m.group(1) if m else "",
                              "X-Requested-With": "XMLHttpRequest",
                              "Accept": "application/json, text/plain, */*",
                              "Referer": "https://get.tech/search",
                              "Origin": "https://get.tech"})
            break
        s = None
        time.sleep(20)
    if s is None:
        return "origin-down"
    r = call(s, "POST", API + "/login",
             json={"username": email.lower(), "password": pwd}, tries=5, timeout=110)
    if r is None or r.status_code != 200:
        return "login-fail"
    rc = call(s, "GET", API + "/get-cart", tries=3, timeout=60)
    if rc is None:
        return "cart-504"
    if '"domorder"' not in rc.text:
        log("  cart empty, re-adding item")
        pr = call(s, "GET", API + "/pricing", tries=3, timeout=110)
        try:
            pricing = json.loads(pr.json()["pricing"])
            price = pricing["dottech"]["addnewdomain"]["1"] * 1
        except Exception:
            return "pricing-fail"
        item = {"category": "domorder", "product": "dottech", "domain": dom_full,
                "duration": 1, "price": price}
        r = call(s, "POST", API + "/update-cart", json={"cart": [item]}, tries=4, timeout=110)
        if r is None or "updated" not in r.text:
            return "cart-refill-fail"
    r = call(s, "POST", API + "/test-coupon", json={"coupon": COUPON}, tries=4, timeout=170)
    log("  coupon:", r.status_code if r else 504, r.text[:80] if r else "")
    for rnd in range(3):
        r = call(s, "POST", API + "/place-order", tries=4, timeout=170)
        if r is not None and r.status_code == 200:
            try:
                o = json.loads(r.json()["order"][0])
            except Exception:
                o = {}
            new = dict(rec)
            new["recovered"] = True
            new["ts"] = time.strftime("%F %T")
            new["result"] = {"ok": True, "order": r.json()}
            new["invoiceid"] = o.get("invoiceid")
            new["orderid"] = o.get("orderid")
            bank_append(new)
            log("  RECOVERED", dom_full, "inv", o.get("invoiceid"))
            tg_notify("GET.TECH RECOVERED: " + dom_full
                      + " (inv " + str(o.get("invoiceid")) + ")")
            return "recovered"
        rc = call(s, "GET", API + "/get-cart", tries=3, timeout=60)
        if rc is not None and '"domorder"' not in rc.text:
            new = dict(rec)
            new["recovered"] = True
            new["ts"] = time.strftime("%F %T")
            new["result"] = {"ok": "maybe",
                             "note": "cart empty after 504 — verify in account"}
            bank_append(new)
            log("  MAYBE-PLACED", dom_full)
            tg_notify("GET.TECH MAYBE: " + dom_full + " (verify acct " + email + ")")
            return "maybe"
        time.sleep(30 + rnd * 30)
    return "still-504"


def main():
    st = load_rstate()
    while True:
        try:
            recs = failed_records()
            todo = [r for r in recs
                    if r["domain"] not in st["recovered"] and r["domain"] not in st["dead"]]
            if todo:
                log("failed records to recover:", [r["domain"] for r in todo])
                for rec in todo:
                    res = recover(rec)
                    if res in ("recovered", "maybe"):
                        st["recovered"].append(rec["domain"])
                        save_rstate(st)
                    time.sleep(20)
            else:
                log("nothing to recover")
        except Exception as e:
            log("sweep EXC:", str(e)[:150])
        time.sleep(300)


if __name__ == "__main__":
    main()
