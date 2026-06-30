"""WeWe RSS setup script: login via QR + add 8 WeChat feeds"""
import json
import os
import time
import urllib.parse
import urllib.request

API_BASE = "http://localhost:4000/trpc"
AUTH_CODE = os.environ.get("WEWE_RSS_AUTH_CODE", "")
if not AUTH_CODE:
    raise SystemExit("Set WEWE_RSS_AUTH_CODE before running this script.")

FEED_URLS = [
    ("中北大学", "https://mp.weixin.qq.com/s/0YmSOixSuEylExsrEW3yeA"),
    ("软件学院新媒体中心", "https://mp.weixin.qq.com/s/nKDtJIqA1Soawrnx4z7pgQ"),
    ("中北大学学生会", "https://mp.weixin.qq.com/s/jBTM2pPVxMFRZSjdLWTrmg"),
    ("中北大学科学院", "https://mp.weixin.qq.com/s/h28Msi-2vYUWDvlx7jgVdA"),
    ("中北大学共青团", "https://mp.weixin.qq.com/s/neFq9kkYtpA_PYBmmdMeZg"),
    ("中北大学图书馆", "https://mp.weixin.qq.com/s/K19o1-1-8OefwbALpVgkiQ"),
    ("享创中北", "https://mp.weixin.qq.com/s/TLHKxW8V5W4wGaLcDq1R-A"),
    ("中北就创", "https://mp.weixin.qq.com/s/_dit9ncG1Cws7gQ6RabNLg"),
]

QUERY_PROCS = {"platform.getLoginResult", "feed.list", "account.list", "article.list"}


def trpc_call(procedure: str, input_data: dict = None) -> dict:
    inp = input_data or {}
    if procedure in QUERY_PROCS:
        enc = urllib.parse.quote(json.dumps(inp))
        req = urllib.request.Request(
            f"{API_BASE}/{procedure}?input={enc}",
            headers={"Authorization": AUTH_CODE},
        )
    else:
        body = json.dumps(inp).encode()
        req = urllib.request.Request(
            f"{API_BASE}/{procedure}", data=body,
            headers={"Content-Type": "application/json", "Authorization": AUTH_CODE},
        )
    raw = json.loads(urllib.request.urlopen(req).read())
    if isinstance(raw, list):
        raw = raw[0]
    result = raw.get("result", {})
    if isinstance(result, dict) and "data" in result:
        return result["data"]
    if isinstance(result, dict) and "json" in result:
        return result["json"]
    v10 = raw.get("0", {})
    if "error" in v10:
        raise Exception(v10["error"]["message"])
    if "json" in v10:
        return v10["json"]
    return v10


def step1_login() -> dict:
    print("\n=== Step 1: Generate QR code ===")
    result = trpc_call("platform.createLoginUrl")
    print(f"QR URL: {result['scanUrl']}")
    try:
        import qrcode
        qr = qrcode.QRCode(border=2, box_size=6)
        qr.add_data(result["scanUrl"])
        qr.print_ascii()
    except ImportError:
        pass
    print("\nScan with phone WeChat (微信读书). DO NOT check '24h auto logout'!")
    uuid = result["uuid"]
    while True:
        time.sleep(3)
        res = trpc_call("platform.getLoginResult", {"id": uuid})
        msg = res.get("message", "")
        print(f"  {msg}")
        if res.get("vid"):
            print(f"  Logged in as: {res.get('username', '')}")
            return res


def step2_add_account(vid, token, name):
    print(f"\n=== Step 2: Add account '{name}' ===")
    r = trpc_call("account.add", {"id": str(vid), "token": token, "name": name})
    print(f"  OK → id={r['id']}")


def step3_add_feeds() -> list:
    print("\n=== Step 3: Add 8 feeds ===")
    feeds = []
    for label, url in FEED_URLS:
        print(f"  {label} ...", end=" ", flush=True)
        try:
            info = trpc_call("platform.getMpInfo", {"wxsLink": url})
            mp = info[0]
            trpc_call("feed.add", {
                "id": mp["id"], "mpName": mp["name"],
                "mpCover": mp.get("cover", ""), "mpIntro": mp.get("intro", ""),
                "updateTime": mp.get("updateTime", int(time.time())),
            })
            print(f"OK ({mp['name']})")
            feeds.append(mp)
        except Exception as e:
            print(f"FAIL: {e}")
    return feeds


def step4_trigger_history(feeds: list):
    print("\n=== Step 4: Fetch history ===")
    for f in feeds:
        name = f.get("name", f["id"])
        print(f"  {name} ...", end=" ", flush=True)
        try:
            trpc_call("feed.getHistoryArticles", {"mpId": f["id"]})
            print("triggered")
            time.sleep(3)
        except Exception as e:
            print(f"FAIL: {e}")


def step5_verify():
    print("\n=== Step 5: Feeds list ===")
    r = trpc_call("feed.list", {"limit": 50})
    for f in r.get("items", []):
        print(f"  [{f['status']}] {f['mpName']}  →  /feeds/{f['id']}.rss")


if __name__ == "__main__":
    login = step1_login()
    step2_add_account(login["vid"], login["token"], login.get("username", "zbdx"))
    feeds = step3_add_feeds()
    step4_trigger_history(feeds)
    time.sleep(3)
    step5_verify()
    print(f"\nDone! RSS: http://43.163.198.120:4000/feeds/all.atom")
