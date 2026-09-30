import os, io, re, time, base64, hashlib, sqlite3, threading, math, datetime as dt
import requests
from flask import Flask, request, jsonify, send_file
from dotenv import load_dotenv
BASE = os.path.dirname(os.path.abspath(__file__))
ENV = os.path.join(BASE, ".env"); DB = os.path.join(BASE, "farm.db")
load_dotenv(ENV, encoding="utf-8-sig")
MODELS = [os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip(), "gemini-2.5-flash-lite", "gemini-2.0-flash", "gemini-flash-latest"]
app = Flask(__name__, static_folder="static", static_url_path="")
state = {"pump": False, "zones": None, "seen": 0, "demo": False, "last_alert": ("ok", 0)}
cache = {}

# ---------- storage ----------
def db():
    c = sqlite3.connect(DB)
    c.execute("create table if not exists kv(k text primary key, v text)")
    c.execute("create table if not exists history(id integer primary key autoincrement, ts text, kind text, body text)")
    return c
def kv_get(k, d=None):
    with db() as c:
        r = c.execute("select v from kv where k=?", (k,)).fetchone()
    return r[0] if r else d
def kv_set(k, v):
    with db() as c: c.execute("insert or replace into kv values(?,?)", (k, str(v)))
def log(kind, body):
    with db() as c: c.execute("insert into history(ts,kind,body) values(?,?,?)", (dt.datetime.now().strftime("%d-%m %H:%M"), kind, body[:600]))
def farm(): return float(kv_get("lat", 11.10)), float(kv_get("lon", 79.65))
def save_env(**kw):
    d = {}
    if os.path.exists(ENV):
        for l in open(ENV, encoding="utf-8-sig"):
            if "=" in l: a, b = l.strip().split("=", 1); d[a] = b
    d.update(kw)
    with open(ENV, "w", encoding="utf-8") as f: f.write("".join(f"{a}={b}\n" for a, b in d.items()))
    os.environ.update(kw)
def key():
    k = os.environ.get("GEMINI_API_KEY", "").strip().strip('"').strip("'").lstrip("\ufeff")
    return "" if k.startswith("paste_") else k

# ---------- gemini ----------
def gemini(parts):
    if not key(): raise RuntimeError("NO_KEY")
    t0, err = time.time(), ""
    for rnd in range(3):
        for m in dict.fromkeys(MODELS):
            if time.time() - t0 > 70: raise RuntimeError("BUSY " + err)
            try:
                r = requests.post(f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent",
                    headers={"x-goog-api-key": key()}, timeout=30,
                    json={"contents": [{"parts": parts}], "generationConfig": {"temperature": 0.3}})
            except requests.RequestException as e:
                err = str(e); continue
            if r.status_code == 200:
                try: return r.json()["candidates"][0]["content"]["parts"][0]["text"]
                except Exception: err = "empty reply"; continue
            err = f"{r.status_code} {r.text[:150]}"
            if r.status_code in (400, 401, 403): raise RuntimeError(err)
        time.sleep(2 * (rnd + 1))
    raise RuntimeError("BUSY " + err)
def clean(t): return re.sub(r"[*#`_>]+", "", t).strip()

# ---------- data: weather, soil, cyclone ----------
def hav(a, b, c, d):
    p = math.pi / 180
    x = math.sin((c - a) * p / 2) ** 2 + math.cos(a * p) * math.cos(c * p) * math.sin((d - b) * p / 2) ** 2
    return 12742 * math.asin(math.sqrt(x))
def om_weather(lat, lon):
    p = dict(latitude=lat, longitude=lon, timezone="Asia/Kolkata", forecast_days=3,
        current="temperature_2m,relative_humidity_2m,wind_speed_10m", hourly="soil_moisture_3_to_9cm",
        daily="precipitation_sum,precipitation_probability_max,wind_speed_10m_max")
    j = requests.get("https://api.open-meteo.com/v1/forecast", params=p, timeout=15).json()
    c, d, h = j["current"], j["daily"], j["hourly"]
    sm = None
    try:
        v = h["soil_moisture_3_to_9cm"][h["time"].index(c["time"][:13] + ":00")]
        sm = None if v is None else round(v * 100)
    except Exception: pass
    return dict(temp=c["temperature_2m"], humidity=c["relative_humidity_2m"], wind=c["wind_speed_10m"],
        rain3d=round(sum(x or 0 for x in d["precipitation_sum"]), 1), wind_max=max(d["wind_speed_10m_max"]),
        rain=d["precipitation_sum"], moisture=sm, moisture_src="modelled")
def cyclones(lat, lon):
    hit = cache.get("cyc")
    if hit and time.time() - hit[0] < 1800: return hit[1]
    out, ok = [], True
    try:
        today = dt.date.today()
        r = requests.get("https://www.gdacs.org/gdacsapi/api/events/geteventlist/SEARCH", timeout=10, params=dict(
            eventlist="TC", fromdate=(today - dt.timedelta(days=4)).isoformat(), todate=today.isoformat(), alertlevel="Green;Orange;Red"))
        for f in r.json().get("features", []):
            p, g = f.get("properties", {}), f.get("geometry", {})
            if p.get("iscurrent") in ("false", False) or g.get("type") != "Point": continue
            x, y = g["coordinates"][:2]; km = round(hav(lat, lon, y, x))
            if km < 1500: out.append(dict(name=p.get("name") or "Tropical cyclone", alert=p.get("alertlevel", "Green"), km=km))
    except Exception: ok = False
    cache["cyc"] = (time.time(), (out, ok)); return out, ok
def level(w):
    l = "danger" if w["rain3d"] > 100 or w["wind_max"] > 62 else "warn" if w["rain3d"] > 40 or w["wind_max"] > 40 else "ok"
    for c in w.get("cyclones", []):
        if c["km"] < 800 and c["alert"] in ("Orange", "Red"): return "danger"
        if l == "ok": l = "warn"
    return l
def demo_weather():
    return dict(temp=27, humidity=91, wind=38, rain3d=118, wind_max=68, rain=[22, 41, 55], moisture=34, moisture_src="modelled",
        cyclones=[dict(name="DEMO cyclone", alert="Red", km=420)], cyc_ok=True, level="danger", demo=True)
def full_weather():
    if state["demo"]: return demo_weather()
    lat, lon = farm(); k = ("w", lat, lon); hit = cache.get(k); stale = False
    if hit and time.time() - hit[0] < 600: w = dict(hit[1])
    else:
        try: w = om_weather(lat, lon); cache[k] = (time.time(), w); w = dict(w)
        except Exception:
            if not hit: raise
            w, stale = dict(hit[1]), True
    w["cyclones"], w["cyc_ok"] = cyclones(lat, lon)
    z = state["zones"]
    if z and time.time() - state["seen"] < 30: w["moisture"], w["moisture_src"] = round(sum(z) / 4), "sensor"
    w["level"], w["demo"], w["stale"] = level(w), False, stale
    return w
def cyc_text(w):
    return ", ".join(f"{c['name']} ({c['alert']}) {c['km']} km தொலைவில்" for c in w["cyclones"]) or "அருகில் புயல் இல்லை"
def alert_text(w):
    t = {"danger": "🚨 புயல் / கனமழை எச்சரிக்கை", "warn": "⚠️ மழை / காற்று கவனம்", "ok": "வானிலை சீராக உள்ளது"}[w["level"]]
    t += f"\nஅடுத்த 3 நாள் மழை {w['rain3d']} mm, அதிக காற்று {w['wind_max']} km/h.\nபுயல்: {cyc_text(w)}"
    if w["level"] != "ok": t += "\nவயலில் வடிகால் தயார் செய்யுங்கள், மோட்டாரை பாதுகாப்பாக வையுங்கள்."
    return ("[DEMO] " if w.get("demo") else "") + t

# ---------- telegram phone alerts ----------
def tg_send(text):
    t, c = os.environ.get("TELEGRAM_TOKEN", ""), os.environ.get("TELEGRAM_CHAT_ID", "")
    if not (t and c): return False, "Telegram இணைக்கப்படவில்லை"
    try:
        r = requests.post(f"https://api.telegram.org/bot{t}/sendMessage", json={"chat_id": c, "text": text}, timeout=15)
        return r.status_code == 200, "" if r.status_code == 200 else r.text[:150]
    except Exception as e: return False, str(e)
def maybe_alert(w):
    l, ts = state["last_alert"]
    if w["level"] == "ok": state["last_alert"] = ("ok", 0); return
    if w["level"] != l or time.time() - ts > 21600:
        if tg_send(alert_text(w))[0]: state["last_alert"] = (w["level"], time.time()); log("alert", alert_text(w))
def worker():
    while True:
        try: maybe_alert(full_weather())
        except Exception: pass
        time.sleep(1800)

# ---------- advice ----------
def stage(a): return "நாற்றங்கால்" if a < 20 else "தூர்கட்டல்" if a < 60 else "பூக்கும் பருவம்" if a < 90 else "அறுவடை நெருங்குகிறது"
def facts(age, w):
    m = w["moisture"]
    return (f"பயிர்: நெல், வயது {age} நாள், நிலை {stage(age)}. வெப்பம் {w['temp']}°C, ஈரப்பதம் {w['humidity']}%, காற்று {w['wind']} km/h. "
        f"அடுத்த 3 நாள் மழை {w['rain3d']} mm, அதிக காற்று {w['wind_max']} km/h. மண் ஈரம் {m if m is not None else 'தெரியவில்லை'}% "
        f"({'சென்சார்' if w['moisture_src'] == 'sensor' else 'கணிப்பு'}). புயல்: {cyc_text(w)}.")
def rule_advice(age, w):
    t = f"பயிர் நிலை {stage(age)}. " + ("கனமழை அல்லது புயல் வாய்ப்பு உள்ளது, வடிகால் தயார் செய்யுங்கள். " if w["level"] != "ok" else "வானிலை சீராக உள்ளது. ")
    m = w["moisture"]
    return t + ("மண் ஈரம் குறைவு, தண்ணீர் பாய்ச்சலாம்." if m is not None and m < 40 and w["rain3d"] < 10 else "இன்று தண்ணீர் தேவையில்லை.")

# ---------- routes ----------
@app.get("/")
def index(): return app.send_static_file("index.html")
@app.get("/api/status")
def status(): return jsonify(key=bool(key()), telegram=bool(os.environ.get("TELEGRAM_CHAT_ID")), demo=state["demo"])
@app.post("/api/setkey")
def setkey():
    k = (request.get_json(force=True).get("key") or "").strip()
    if len(k) < 20: return jsonify(error="key மிகச் சிறியது"), 400
    save_env(GEMINI_API_KEY=k)
    try: gemini([{"text": "hi"}]); return jsonify(ok=True)
    except Exception as e: return jsonify(error=str(e)), 400
@app.post("/api/settelegram")
def settg():
    t = (request.get_json(force=True).get("token") or "").strip()
    try:
        r = requests.get(f"https://api.telegram.org/bot{t}/getUpdates", timeout=15).json()
    except Exception as e: return jsonify(error=str(e)), 400
    if not r.get("ok"): return jsonify(error="Token தவறு"), 400
    ids = [u["message"]["chat"]["id"] for u in r["result"] if "message" in u]
    if not ids: return jsonify(error="முதலில் உங்கள் bot க்கு Telegram இல் 'hi' அனுப்புங்கள், பிறகு மீண்டும் சேமிக்கவும்"), 400
    save_env(TELEGRAM_TOKEN=t, TELEGRAM_CHAT_ID=str(ids[-1]))
    ok, e = tg_send("✅ உங்கள் விவசாயி இணைக்கப்பட்டது. புயல் / மழை எச்சரிக்கைகள் இங்கே வரும்.")
    return jsonify(ok=True, chat_id=str(ids[-1])) if ok else (jsonify(error=e), 400)
@app.post("/api/testalert")
def testalert():
    ok, e = tg_send(alert_text(full_weather()))
    return jsonify(ok=True) if ok else (jsonify(error=e), 400)
@app.route("/api/farm", methods=["GET", "POST"])
def farm_route():
    if request.method == "POST":
        b = request.get_json(force=True); kv_set("lat", float(b["lat"])); kv_set("lon", float(b["lon"])); cache.clear()
    lat, lon = farm(); return jsonify(lat=lat, lon=lon)
@app.post("/api/demo")
def demo():
    state["demo"] = bool(request.get_json(force=True).get("on")); state["last_alert"] = ("ok", 0)
    if state["demo"]: maybe_alert(demo_weather())
    return jsonify(on=state["demo"])
@app.get("/api/weather")
def weather():
    try:
        w = full_weather(); maybe_alert(w); return jsonify(w)
    except Exception as e: return jsonify(error="வானிலை கிடைக்கவில்லை: " + str(e)[:120]), 502
@app.post("/api/advice")
def advice():
    age = int(request.get_json(force=True).get("age", 30))
    try: w = full_weather()
    except Exception as e: return jsonify(error=str(e)), 502
    f = facts(age, w); ck = hashlib.md5(f.encode()).hexdigest(); hit = cache.get(ck)
    if hit and time.time() - hit[0] < 1200: return jsonify(advice=hit[1], source="cache")
    try:
        t = clean(gemini([{"text": "நீ தமிழ்நாட்டு நெல் விவசாய ஆலோசகர். இந்த தகவலை வைத்து எளிய பேச்சுத் தமிழில், 5 வாக்கியத்திற்குள், இன்று செய்ய வேண்டியவை சொல்: "
            "தண்ணீர் பாய்ச்சவா, மழை/புயல் எச்சரிக்கை, உரம்/அறுவடை. குறியீடுகள் பயன்படுத்தாதே. தெரியாததை ஊகிக்காதே.\n" + f}]))
        cache[ck] = (time.time(), t); src, err = "gemini", ""
    except Exception as e: t, src, err = rule_advice(age, w), "rules", str(e)
    log("advice", t); return jsonify(advice=t, source=src, error=err)
@app.post("/api/ask")
def ask():
    b = request.get_json(force=True); q = (b.get("q") or "").strip()
    if not q: return jsonify(error="கேள்வி இல்லை"), 400
    try: w = full_weather()
    except Exception as e: return jsonify(error=str(e)), 502
    try:
        t = clean(gemini([{"text": "நீ 'உங்கள் விவசாயி' குரல் உதவியாளர். பண்ணை தகவலை பயன்படுத்தி எளிய பேச்சுத் தமிழில் 4 வாக்கியத்திற்குள் பதில் சொல். "
            f"குறியீடுகள் பயன்படுத்தாதே. தெரியாவிட்டால் தெரியாது என்று சொல்.\nபண்ணை தகவல்: {facts(int(b.get('age', 30)), w)}\nகேள்வி: {q}"}]))
        log("ask", f"கே: {q}\nப: {t}"); return jsonify(answer=t)
    except Exception as e:
        return jsonify(answer=rule_advice(int(b.get("age", 30)), w), source="rules", error=str(e))
@app.post("/api/diagnose")
def diagnose():
    fl = request.files.get("image")
    if not fl: return jsonify(error="படம் தேர்வு செய்யவும்"), 400
    crop = request.form.get("crop", "").strip()
    img = base64.b64encode(fl.read()).decode()
    prompt = ("நீ அனுபவமுள்ள தாவர நோய் நிபுணர். படத்தை கவனமாக பார்த்து எளிய தமிழில் பதில் சொல். விதிகள்:\n"
        "1) படத்தில் இலை அல்லது செடி தெளிவாக இல்லை என்றால், 'படம் தெளிவில்லை. ஒரு இலையை அருகில், பகல் வெளிச்சத்தில் எடுக்கவும்' என்று மட்டும் சொல்.\n"
        + (f"2) விவசாயி சொன்ன பயிர்: {crop}. படம் வேறு பயிர் போல இருந்தால் அதை சொல்.\n" if crop and crop != "தெரியாது" else "2) பயிர் என்ன என்று சொல்.\n") +
        "3) முதலில் தெரியும் அறிகுறிகளை விவரி: புள்ளி நிறம், வடிவம், எங்கே உள்ளது.\n"
        "4) பிறகு சாத்தியமான நோய் அல்லது பூச்சி 1 அல்லது 2 சொல், ஒவ்வொன்றுக்கும் நம்பிக்கை சதவீதம். 60 சதவீதத்திற்கு கீழ் என்றால் 'உறுதியாக சொல்ல முடியாது' என்று சொல். இலை ஆரோக்கியமாக இருந்தால் அப்படியே சொல்.\n"
        "5) சிகிச்சை: இயற்கை முறை முதலில். ரசாயன மருந்து தேவைப்பட்டால் வேளாண் அலுவலர் ஆலோசனையுடன் என்று சொல். மருந்தளவு சொல்லாதே.\n"
        "6) கடைசி வரி: உறுதி செய்ய உள்ளூர் வேளாண் அலுவலரிடம் காட்டுங்கள்.\n"
        "குறியீடுகள் (*, #) பயன்படுத்தாதே. ஊகிக்காதே.")
    try:
        t = clean(gemini([{"text": prompt}, {"inline_data": {"mime_type": fl.mimetype or "image/jpeg", "data": img}}]))
        log("disease", (crop + ": " if crop else "") + t); return jsonify(result=t)
    except Exception as e:
        m = str(e)
        if m == "NO_KEY": m = "முதலில் Gemini key சேமிக்கவும்"
        elif m.startswith("BUSY") or "503" in m or "429" in m: m = "Gemini இப்போது மிகவும் பிஸியாக உள்ளது. 30 வினாடி கழித்து மீண்டும் படத்தை தேர்வு செய்யவும்."
        else: m = "Gemini பிழை: " + m[:150]
        return jsonify(error=m), 400
@app.get("/api/history")
def history():
    with db() as c: rows = c.execute("select ts,kind,body from history order by id desc limit 40").fetchall()
    return jsonify([dict(ts=a, kind=b, body=c_) for a, b, c_ in rows])
@app.get("/api/tts")
def tts():
    from gtts import gTTS
    t = clean(request.args.get("text", ""))[:700]; lang = "en" if request.args.get("lang") == "en" else "ta"
    k = hashlib.md5((lang + t).encode()).hexdigest()
    if k not in cache:
        buf = io.BytesIO(); gTTS(t, lang=lang).write_to_fp(buf); cache[k] = (time.time(), buf.getvalue())
    return send_file(io.BytesIO(cache[k][1]), mimetype="audio/mpeg")
@app.route("/api/sensor", methods=["GET", "POST"])
def sensor():
    if request.method == "POST":
        z = request.get_json(force=True).get("zones")
        if isinstance(z, list) and len(z) == 4: state["zones"], state["seen"] = [float(x) for x in z], time.time()
        return jsonify(ok=True)
    return jsonify(zones=state["zones"], fresh=time.time() - state["seen"] < 30)
@app.route("/api/pump", methods=["GET", "POST"])
def pump():
    if request.method == "POST": state["pump"] = bool(request.get_json(force=True).get("on"))
    return jsonify(on=state["pump"])

if not os.environ.get("NO_WORKER"): threading.Thread(target=worker, daemon=True).start()
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=False)
