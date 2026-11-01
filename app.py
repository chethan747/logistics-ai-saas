"""Complete SaaS model for AI logistics & delivery tracking (trucks).
Pure Python stdlib only. Demo / prototype SaaS, NOT production-ready:
no real payments, no real GPS feed, demo logins only, simulated data.
Run:  python3 app.py
Then open: http://localhost:8000/  and  http://localhost:8000/dashboard
API: GET /api/shipments | GET /api/eta?id=TRK-101 | POST /api/gps-ping
"""
import json, math, sqlite3, os
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs

DB = os.path.join(os.path.dirname(__file__), "logistics.db")

# ---------- AI ETA MODEL (refined spec v1) ----------
def clamp(x, lo, hi):
    return max(lo, min(hi, x))

def predict_eta(shipment):
    """Return predicted delivery, window, confidence, delay risk, reasons.
    Baseline = remaining_distance / 55 mph, no adjustments.
    Model    = remaining / effective_speed + dwell_remaining, adjusted for
               traffic, weather, lane history and driver history.
    """
    remaining = float(shipment["remaining_miles"])
    speed = float(shipment.get("speed_mph") or 55)
    traffic = float(shipment.get("traffic_factor", 1.0))   # >1 = slower
    weather = float(shipment.get("weather_factor", 1.0))   # >1 = slower
    lane = float(shipment.get("lane_factor", 1.0))
    driver = float(shipment.get("driver_factor", 1.0))
    dwell = float(shipment.get("dwell_remaining_min", 0))
    gps_age = float(shipment.get("gps_age_min", 0))

    baseline_min = remaining / 55.0 * 60
    # Dampened factors: raw traffic/weather multipliers overstate delay if
    # multiplied fully (a known calibration trap). Learned weights in a real
    # model would replace these fixed dampeners.
    combined = 1 + 0.5 * (traffic - 1) + 0.4 * (weather - 1) + 0.3 * (lane - 1) + 0.2 * (driver - 1)
    eff_speed = speed / max(0.7, combined)
    eff_speed = clamp(eff_speed, 20, 70)
    model_min = remaining / eff_speed * 60 + dwell

    # Confidence shrinks with bad traffic/weather and stale GPS
    conf = 0.92 - 0.10 * max(0, traffic - 1) - 0.08 * max(0, weather - 1)
    if gps_age > 15:
        conf -= 0.20
    elif gps_age > 5:
        conf -= 0.08
    conf = clamp(conf, 0.45, 0.95)

    # Window half-width grows as confidence falls
    half = model_min * (1 - conf) * 1.2 + 8
    # Delay probability: logistic-ish on overrun vs scheduled window
    sched_min = float(shipment.get("scheduled_remaining_min", model_min))
    overrun = model_min - sched_min
    delay_prob = 1 / (1 + math.exp(-overrun / 30.0)) if overrun != 0 else 0.5
    delay_prob = clamp(delay_prob, 0.02, 0.98)

    reasons = []
    if traffic > 1.15: reasons.append("traffic")
    if weather > 1.1: reasons.append("weather")
    if dwell > 30: reasons.append("long dwell / loading")
    if gps_age > 15: reasons.append("GPS signal stale")
    if overrun > 30: reasons.append("behind schedule")
    if not reasons: reasons.append("on schedule")

    now = datetime.now(timezone.utc)
    pred = now + timedelta(minutes=model_min)
    status = "on_time"
    if delay_prob > 0.65 or overrun > 30: status = "delayed"
    elif delay_prob > 0.45 or overrun > 10: status = "at_risk"

    return {
        "shipment_id": shipment["id"],
        "baseline_minutes": round(baseline_min, 1),
        "predicted_minutes": round(model_min, 1),
        "predicted_delivery_utc": pred.isoformat(),
        "window_minutes": [round(model_min - half, 1), round(model_min + half, 1)],
        "confidence": round(conf, 2),
        "delay_probability": round(delay_prob, 2),
        "delay_reasons": reasons,
        "status": status,
        "gps_stale": gps_age > 15,
    }

# ---------- STORE ----------
def init_db():
    con = sqlite3.connect(DB); c = con.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS users
        (email TEXT PRIMARY KEY, role TEXT, tenant TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS shipments
        (id TEXT PRIMARY KEY, tenant TEXT, origin TEXT, destination TEXT,
         driver TEXT, vehicle TEXT, status TEXT, remaining_miles REAL,
         speed_mph REAL, traffic_factor REAL, weather_factor REAL,
         lane_factor REAL, driver_factor REAL, dwell_remaining_min REAL,
         gps_age_min REAL, scheduled_remaining_min REAL,
         actual_minutes REAL)""")
    users = [("admin@demo.local", "admin", "Demo Fleet"),
             ("dispatcher@demo.local", "dispatcher", "Demo Fleet"),
             ("driver@demo.local", "driver", "Demo Fleet"),
             ("customer@demo.local", "customer", "Demo Fleet")]
    c.executemany("INSERT OR IGNORE INTO users VALUES (?,?,?)", users)
    seeds = [
        ("TRK-101", "Columbus, OH", "Chicago, IL", "A. Kumar", "Truck-07", "in_transit", 180, 58, 1.25, 1.0, 1.05, 0.98, 20, 2, 210, 238),
        ("TRK-102", "Columbus, OH", "Cleveland, OH", "M. Lee", "Truck-03", "in_transit", 65, 52, 1.0, 1.15, 1.0, 1.02, 15, 4, 95, 102),
        ("TRK-103", "Chicago, IL", "Detroit, MI", "S. Patel", "Truck-11", "in_transit", 240, 60, 1.4, 1.2, 1.1, 1.0, 45, 18, 260, 315),
        ("TRK-104", "Columbus, OH", "Cincinnati, OH", "J. Smith", "Truck-02", "out_for_delivery", 28, 38, 1.0, 1.0, 0.98, 0.95, 10, 1, 45, 42),
        ("TRK-105", "Indianapolis, IN", "Columbus, OH", "R. Davis", "Truck-09", "in_transit", 120, 55, 1.1, 1.0, 1.02, 1.05, 0, 3, 145, 150),
        ("TRK-106", "Chicago, IL", "Columbus, OH", "T. Nguyen", "Truck-05", "delivered", 0, 0, 1.0, 1.0, 1.0, 1.0, 0, 0, 0, 355),
        ("TRK-107", "Detroit, MI", "Cleveland, OH", "K. Jones", "Truck-08", "in_transit", 95, 50, 1.3, 1.0, 1.08, 1.0, 25, 6, 115, 138),
        ("TRK-108", "Columbus, OH", "Pittsburgh, PA", "L. Brown", "Truck-04", "picked_up", 185, 0, 1.0, 1.0, 1.0, 1.0, 40, 2, 220, 228),
    ]
    c.executemany("INSERT OR REPLACE INTO shipments VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  [("Demo Fleet",) + (s[0],) + s[1:] if False else (s[0], "Demo Fleet") + s[1:] for s in seeds])
    # The above seeds already include tenant as 2nd field; fix order by re-inserting correctly:
    con.commit(); con.close()
    # Rebuild cleanly to avoid column-order confusion
    con = sqlite3.connect(DB); c = con.cursor()
    c.execute("DELETE FROM shipments")
    rows = []
    for s in seeds:
        rows.append((s[0], "Demo Fleet", s[1], s[2], s[3], s[4], s[5], s[6], s[7], s[8], s[9], s[10], s[11], s[12], s[13], s[14], s[15]))
    c.executemany("INSERT INTO shipments VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    con.commit(); con.close()
    init_v2_tables()

def all_shipments():
    con = sqlite3.connect(DB); con.row_factory = sqlite3.Row
    rows = [dict(r) for r in con.execute("SELECT * FROM shipments ORDER BY id")]
    con.close()
    out = []
    for r in rows:
        p = predict_eta(r) if r["remaining_miles"] > 0 else None
        out.append({**r, "eta": p})
    return out

def analytics():
    ships = all_shipments()
    active = [s for s in ships if s["status"] != "delivered"]
    statuses = {}
    for s in ships:
        st = (s["eta"]["status"] if s["eta"] else "delivered")
        statuses[st] = statuses.get(st, 0) + 1
    # MAE on completed / seeded trips where actual is known and predicted was stored approx:
    errs = []
    for s in ships:
        if s["eta"]:
            errs.append(abs(s["eta"]["predicted_minutes"] - s["actual_minutes"]) if s["actual_minutes"] else 0)
    mae_model = round(sum(errs) / len(errs), 1) if errs else 0
    base_errs = []
    for s in ships:
        if s["eta"]:
            base_errs.append(abs(s["eta"]["baseline_minutes"] - (s["actual_minutes"] or s["eta"]["baseline_minutes"])))
    mae_base = round(sum(base_errs) / len(base_errs), 1) if base_errs else 0
    return {"total": len(ships), "active": len(active), "by_status": statuses,
            "mae_model_min": mae_model, "mae_baseline_min": mae_base}

# ---------- V2 FEATURES (working demo form, stdlib only) ----------
def init_v2_tables(con=None):
    if con is None:
        con = sqlite3.connect(DB)
    c = con.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS stops
        (shipment_id TEXT, seq INTEGER, place TEXT, miles_from_current REAL, priority INTEGER)""")
    c.execute("""CREATE TABLE IF NOT EXISTS pods
        (shipment_id TEXT PRIMARY KEY, method TEXT, signature_name TEXT, otp TEXT, photo_ref TEXT, recorded_at TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS notifications
        (id INTEGER PRIMARY KEY AUTOINCREMENT, shipment_id TEXT, channel TEXT, kind TEXT, message TEXT)""")
    c.execute("DELETE FROM stops"); c.execute("DELETE FROM notifications")
    stops = [
        ("TRK-101", 1, "Toledo, OH depot", 60, 2), ("TRK-101", 2, "Fort Wayne, IN hub", 130, 1),
        ("TRK-103", 1, "Toledo, OH depot", 90, 1), ("TRK-103", 2, "Ann Arbor, MI hub", 170, 2),
        ("TRK-104", 1, "Cincinnati, OH customer", 28, 1),
    ]
    c.executemany("INSERT INTO stops VALUES (?,?,?,?,?)", stops)
    # POD for the one delivered seed shipment
    c.execute("INSERT OR REPLACE INTO pods VALUES (?,?,?,?,?,?)",
              ("TRK-106", "signature", "R. Davis", "482913", "pod_TRK-106.jpg", "2026-11-01T12:00:00Z"))
    # Notifications generated from current AI status (demo log, not real SMS/email)
    for s in all_shipments():
        eta = s["eta"]
        if not eta: continue
        if eta["status"] == "delayed":
            msg = f"Delay alert: {s['id']} may miss its window ({', '.join(eta['delay_reasons'])})."
            c.execute("INSERT INTO notifications (shipment_id, channel, kind, message) VALUES (?,?,?,?)", (s["id"], "sms", "delay_alert", msg))
            c.execute("INSERT INTO notifications (shipment_id, channel, kind, message) VALUES (?,?,?,?)", (s["id"], "email", "delay_alert", msg))
        elif eta["status"] == "at_risk":
            c.execute("INSERT INTO notifications (shipment_id, channel, kind, message) VALUES (?,?,?,?)",
                      (s["id"], "email", "at_risk_warning", f"At-risk warning: {s['id']} ETA window is slipping."))
        if eta["gps_stale"]:
            c.execute("INSERT INTO notifications (shipment_id, channel, kind, message) VALUES (?,?,?,?)",
                      (s["id"], "email", "gps_stale", f"GPS stale for {s['id']}: last ping over 15 minutes ago."))
    con.commit(); con.close()

def optimise_route(stops):
    """Route-optimisation STUB (demo): nearest-first, then priority.
    This is not a TSP solver; it orders stops deterministically so the
    demo is testable. A production version would use OR-Tools / routing.
    Returns list of stop dicts in optimised order."""
    ordered = sorted(stops, key=lambda s: (s["miles_from_current"], -s["priority"]))
    total = sum(s["miles_from_current"] for s in ordered)
    return {"optimised_order": [s["place"] for s in ordered], "stops": ordered, "total_miles_estimate": total}

def get_stops(shipment_id):
    con = sqlite3.connect(DB); con.row_factory = sqlite3.Row
    rows = [dict(r) for r in con.execute("SELECT * FROM stops WHERE shipment_id=? ORDER BY seq", (shipment_id,))]
    con.close(); return rows

def get_pod(shipment_id):
    con = sqlite3.connect(DB); con.row_factory = sqlite3.Row
    r = con.execute("SELECT * FROM pods WHERE shipment_id=?", (shipment_id,)).fetchone()
    con.close(); return dict(r) if r else None

def record_pod(shipment_id, method, signature_name="", otp="", photo_ref=""):
    con = sqlite3.connect(DB)
    con.execute("INSERT OR REPLACE INTO pods VALUES (?,?,?,?,?,?)",
                (shipment_id, method, signature_name, otp, photo_ref, datetime.now(timezone.utc).isoformat()))
    con.execute("UPDATE shipments SET status='delivered', remaining_miles=0 WHERE id=?", (shipment_id,))
    con.commit(); con.close()
    return get_pod(shipment_id)

def list_notifications(shipment_id=None):
    con = sqlite3.connect(DB); con.row_factory = sqlite3.Row
    q = "SELECT * FROM notifications ORDER BY id" if not shipment_id else "SELECT * FROM notifications WHERE shipment_id=? ORDER BY id"
    args = () if not shipment_id else (shipment_id,)
    rows = [dict(r) for r in con.execute(q, args)]; con.close(); return rows

def fleet_analytics():
    ships = all_shipments()
    by_driver, by_vehicle = {}, {}
    for s in ships:
        for key, bucket in (("driver", by_driver), ("vehicle", by_vehicle)):
            b = bucket.setdefault(s[key], {"shipments": 0, "delivered": 0, "active": 0, "on_time_proxy": 0, "errors": []})
            b["shipments"] += 1
            if s["status"] == "delivered": b["delivered"] += 1
            else: b["active"] += 1
            if s["eta"]:
                b["errors"].append(abs(s["eta"]["predicted_minutes"] - s["actual_minutes"]))
                if s["eta"]["predicted_minutes"] <= s["scheduled_remaining_min"] + 30: b["on_time_proxy"] += 1
    for bucket in (by_driver, by_vehicle):
        for b in bucket.values():
            b["avg_abs_error_min"] = round(sum(b["errors"]) / len(b["errors"]), 1) if b["errors"] else 0
            del b["errors"]
    return {"by_driver": by_driver, "by_vehicle": by_vehicle}

def shipment_detail(shipment_id):
    s = next((x for x in all_shipments() if x["id"] == shipment_id), None)
    if not s: return None
    stops = get_stops(shipment_id)
    return {**s, "stops": stops, "route": optimise_route(stops) if stops else None,
            "pod": get_pod(shipment_id), "notifications": list_notifications(shipment_id)}

# ---------- WEB ----------
def page(title, body):
    return f"""<!doctype html><html><head><meta charset='utf-8'>
    <title>{title}</title><style>
    body{{font-family:system-ui,sans-serif;max-width:980px;margin:24px auto;padding:0 16px}}
    table{{border-collapse:collapse;width:100%}} td,th{{border:1px solid #ddd;padding:8px;text-align:left}}
    .card{{border:1px solid #ddd;border-radius:12px;padding:16px;margin:12px 0}}
    a{{color:#0b5fff}} .pill{{padding:2px 8px;border-radius:999px;background:#eef2ff}}
    </style></head><body><h1>{title}</h1>{body}
    <p><a href='/'>Home</a> · <a href='/dashboard'>Dashboard</a> · <a href='/portal'>Customer Portal</a> · <a href='/analytics'>Analytics</a> · <a href='/fleet'>Fleet</a> · <a href='/notifications'>Notifications</a> · <a href='/pricing'>Pricing</a> · <a href='/api/shipments'>API JSON</a></p>
    <p><small>Demo SaaS — simulated data, demo logins only. Not production, no real payments or GPS.</small></p></body></html>"""

class H(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="text/html"):
        b = body.encode() if isinstance(body, str) else body
        self.send_response(code); self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        u = urlparse(self.path); q = parse_qs(u.query)
        if u.path == "/":
            self._send(200, page("Logistics AI — SaaS", """
            <div class='card'><p><b>One AI product for truck delivery tracking.</b> Live tracking, predictive ETA windows, delay alerts, customer tracking, and analytics — for small fleets first.</p>
            <p>Demo logins (any password works in demo): admin@demo.local · dispatcher@demo.local · driver@demo.local · customer@demo.local</p>
            <p><a href='/dashboard'>Open dispatcher dashboard →</a></p></div>
            <div class='card'><h3>SaaS modules</h3><ul>
            <li>Shipments & live tracking</li><li>AI ETA + delay risk</li><li>Alerts & customer portal</li>
            <li>Proof of delivery · Route optimisation (nearest-first stub) · Fleet analytics · Notifications log · Customer portal</li></ul></div>"""))
        elif u.path == "/dashboard":
            a = analytics()
            filt = q.get("status", ["all"])[0]; search = q.get("q", [""])[0].lower()
            ships = all_shipments()
            def ai_status(s): return s["eta"]["status"] if s["eta"] else "delivered"
            if filt != "all": ships = [s for s in ships if ai_status(s) == filt]
            if search: ships = [s for s in ships if search in s["id"].lower() or search in s["origin"].lower() or search in s["destination"].lower() or search in s["driver"].lower() or search in s["vehicle"].lower()]
            summary = "".join(f"<div class='card'><b>{k}</b><br>{v}</div>" for k, v in [("Total", a["total"]), ("Active", a["active"]), ("Model MAE (demo)", f"{a['mae_model_min']} min"), ("Baseline MAE (demo)", f"{a['mae_baseline_min']} min")] + [(k, v) for k, v in a["by_status"].items()])
            rows = "".join(f"<tr><td>{s['id']}</td><td>{s['origin']} → {s['destination']}</td><td>{s['driver']} / {s['vehicle']}</td><td>{s['status']}</td><td>{s['eta']['predicted_minutes'] if s['eta'] else '—'} min</td><td>{s['eta']['confidence'] if s['eta'] else '—'}</td><td>{ai_status(s)}</td><td><a href='/shipment?id={s['id']}'>Detail</a> · <a href='/track?id={s['id']}'>Track</a></td></tr>" for s in ships)
            filters = "Filter: " + " ".join(f"<a href='/dashboard?status={x}'>{x}</a>" for x in ["all", "on_time", "at_risk", "delayed", "delivered"])
            self._send(200, page("Dispatcher Dashboard", f"<div>{summary}</div><form method='get' action='/dashboard'>Search: <input name='q' value='{q.get('q',[''])[0]}'> <input type='submit' value='Search'></form><p>{filters}</p><table><tr><th>ID</th><th>Route</th><th>Driver / Vehicle</th><th>Status</th><th>ETA min</th><th>Confidence</th><th>AI status</th><th></th></tr>{rows}</table><p>Showing {len(ships)} shipment(s). Simulated demo data only.</p>"))
        elif u.path == "/shipment":
            d = shipment_detail(q.get("id", ["TRK-101"])[0])
            if not d: return self._send(404, page("Not found", "<p>Shipment not found.</p>"))
            stops = "<br>".join(f"{s['place']} — {s['miles_from_current']} mi (priority {s['priority']})" for s in d["stops"]) or "No multi-stop data"
            route = f"<p>Optimised order (nearest-first stub): {d['route']['optimised_order'] if d['route'] else '—'}</p>" if d["route"] else ""
            pod = f"<pre>{json.dumps(d['pod'], indent=2)}</pre>" if d["pod"] else "<p>No proof of delivery yet.</p>"
            notifs = "<br>".join(f"[{n['channel']}] {n['kind']}: {n['message']}" for n in d["notifications"]) or "No notifications"
            self._send(200, page(f"Shipment {d['id']}", f"<div class='card'><p>{d['origin']} → {d['destination']} · {d['driver']} / {d['vehicle']} · {d['status']}</p><pre>{json.dumps(d['eta'], indent=2)}</pre><h3>Stops</h3><p>{stops}</p>{route}<h3>Proof of delivery</h3>{pod}<h3>Notifications</h3><p>{notifs}</p><form method='post' action='/api/pod'><input type='hidden' name='id' value='{d['id']}'><input name='method' placeholder='signature / photo / otp' value='signature'> <input name='signature_name' placeholder='Signed by'> <input name='otp' placeholder='OTP'> <input type='submit' value='Record POD (demo form)'></form></div>"))
        elif u.path == "/portal":
            rows = "".join(f"<tr><td>{s['id']}</td><td>{s['origin']} → {s['destination']}</td><td>{s['status']}</td><td>{s['eta']['window_minutes'] if s['eta'] else 'Delivered'}</td><td>{s['eta']['status'] if s['eta'] else 'delivered'}</td><td><a href='/track?id={s['id']}'>Track</a></td></tr>" for s in all_shipments())
            self._send(200, page("Customer Portal", f"<p>Customer view: routes, status and ETA windows only — no driver internals.</p><table><tr><th>ID</th><th>Route</th><th>Status</th><th>ETA window (min)</th><th>AI status</th><th></th></tr>{rows}</table>"))
        elif u.path == "/fleet":
            f = fleet_analytics()
            drows = "".join(f"<tr><td>{k}</td><td>{v['shipments']}</td><td>{v['delivered']}</td><td>{v['active']}</td><td>{v['on_time_proxy']}</td><td>{v['avg_abs_error_min']}</td></tr>" for k, v in f["by_driver"].items())
            vrows = "".join(f"<tr><td>{k}</td><td>{v['shipments']}</td><td>{v['delivered']}</td><td>{v['active']}</td><td>{v['on_time_proxy']}</td><td>{v['avg_abs_error_min']}</td></tr>" for k, v in f["by_vehicle"].items())
            self._send(200, page("Fleet Analytics", f"<h3>Per driver</h3><table><tr><th>Driver</th><th>Shipments</th><th>Delivered</th><th>Active</th><th>On-time proxy</th><th>Avg abs error (min)</th></tr>{drows}</table><h3>Per vehicle</h3><table><tr><th>Vehicle</th><th>Shipments</th><th>Delivered</th><th>Active</th><th>On-time proxy</th><th>Avg abs error (min)</th></tr>{vrows}</table><p>On-time proxy = predicted within scheduled + 30 min, on simulated demo data.</p>"))
        elif u.path == "/notifications":
            rows = "".join(f"<tr><td>{n['shipment_id']}</td><td>{n['channel']}</td><td>{n['kind']}</td><td>{n['message']}</td></tr>" for n in list_notifications())
            self._send(200, page("Notifications Log (demo — not real SMS/email)", f"<table><tr><th>Shipment</th><th>Channel</th><th>Kind</th><th>Message</th></tr>{rows}</table>"))
        elif u.path == "/analytics":
            a = analytics()
            self._send(200, page("Analytics", f"<div class='card'><p>Total shipments: {a['total']} · Active: {a['active']}</p><p>By AI status: {a['by_status']}</p><p>Model MAE (demo, seeded): {a['mae_model_min']} min · Baseline MAE: {a['mae_baseline_min']} min</p><p>Note: MAE here is on simulated demo data, not real fleet data. Real accuracy must be measured on a pilot fleet.</p><p><a href='/fleet'>Fleet analytics →</a></p></div>"))
        elif u.path == "/pricing":
            self._send(200, page("Pricing — to test after pilot", """
            <div class='card'><b>Starter</b> — up to 10 vehicles — per-vehicle / month, to be priced after pilot</div>
            <div class='card'><b>Growth</b> — up to 50 vehicles — + route optimisation + POD</div>
            <div class='card'><b>Scale</b> — unlimited — + API, TMS integrations, multi-modal</div>
            <p>Pricing is intentionally not locked in this demo. Test it with pilot fleets first.</p>"""))
        elif u.path == "/track":
            sid = q.get("id", ["TRK-101"])[0]
            s = next((x for x in all_shipments() if x["id"] == sid), None)
            if not s: return self._send(404, page("Not found", "<p>Shipment not found.</p>"))
            self._send(200, page(f"Track {sid}", f"<div class='card'><p>{s['origin']} → {s['destination']}</p><p>Driver: {s['driver']} · Vehicle: {s['vehicle']} · Status: {s['status']}</p><pre>{json.dumps(s['eta'], indent=2)}</pre></div>"))
        elif u.path == "/api/shipments":
            self._send(200, json.dumps(all_shipments(), indent=2), "application/json")
        elif u.path == "/api/eta":
            sid = q.get("id", ["TRK-101"])[0]
            s = next((x for x in all_shipments() if x["id"] == sid), None)
            if not s: return self._send(404, json.dumps({"error": "not found"}), "application/json")
            self._send(200, json.dumps(s["eta"], indent=2), "application/json")
        elif u.path == "/api/analytics":
            self._send(200, json.dumps(analytics(), indent=2), "application/json")
        elif u.path == "/api/shipment":
            d = shipment_detail(q.get("id", ["TRK-101"])[0])
            if not d: return self._send(404, json.dumps({"error": "not found"}), "application/json")
            self._send(200, json.dumps(d, indent=2), "application/json")
        elif u.path == "/api/route":
            d = shipment_detail(q.get("id", ["TRK-101"])[0])
            if not d: return self._send(404, json.dumps({"error": "not found"}), "application/json")
            self._send(200, json.dumps(d["route"] or {"optimised_order": [], "stops": [], "total_miles_estimate": 0}, indent=2), "application/json")
        elif u.path == "/api/pod":
            sid = q.get("id", ["TRK-106"])[0]
            self._send(200, json.dumps(get_pod(sid), indent=2), "application/json")
        elif u.path == "/api/notifications":
            self._send(200, json.dumps(list_notifications(q.get("id", [None])[0]), indent=2), "application/json")
        elif u.path == "/api/fleet":
            self._send(200, json.dumps(fleet_analytics(), indent=2), "application/json")
        else:
            self._send(404, page("Not found", "<p>Try /dashboard</p>"))
    def do_POST(self):
        if self.path == "/api/pod":
            n = int(self.headers.get("Content-Length", 0)); raw = self.rfile.read(n).decode()
            data = parse_qs(raw)
            pod = record_pod(data.get("id", ["TRK-101"])[0], data.get("method", ["signature"])[0],
                             data.get("signature_name", [""])[0], data.get("otp", [""])[0], data.get("photo_ref", [""])[0])
            self._send(200, json.dumps({"ok": True, "pod": pod}, indent=2), "application/json")
        elif self.path == "/api/gps-ping":
            n = int(self.headers.get("Content-Length", 0)); data = json.loads(self.rfile.read(n) or b"{}")
            con = sqlite3.connect(DB); con.execute("UPDATE shipments SET remaining_miles=?, speed_mph=?, gps_age_min=? WHERE id=?",
                (data.get("remaining_miles", 100), data.get("speed_mph", 55), data.get("gps_age_min", 0), data.get("id", "TRK-101"))); con.commit(); con.close()
            s = next((x for x in all_shipments() if x["id"] == data.get("id", "TRK-101")), None)
            self._send(200, json.dumps({"ok": True, "eta": s["eta"] if s else None}, indent=2), "application/json")
        else:
            self._send(404, json.dumps({"error": "not found"}), "application/json")
    def log_message(self, *a): pass

if __name__ == "__main__":
    init_db()
    print("Logistics AI SaaS running at http://localhost:8000/  (Ctrl-C to stop)")
    HTTPServer(("127.0.0.1", 8000), H).serve_forever()
