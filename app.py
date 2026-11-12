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
    c.execute("""CREATE TABLE IF NOT EXISTS dock_slots
        (id TEXT PRIMARY KEY, facility TEXT, dock_door TEXT, slot_time TEXT, status TEXT, shipment_id TEXT)""")
    c.execute("DELETE FROM stops"); c.execute("DELETE FROM notifications"); c.execute("DELETE FROM dock_slots")
    seed_demand_history(con)
    seed_safety_events(con)
    seed_temp_readings(con)
    dock = []
    for facility, door in [("Columbus DC", "A1"), ("Chicago DC", "B1"), ("Detroit DC", "C1"), ("Cincinnati DC", "D1")]:
        for i, t in enumerate(["08:00", "10:00", "12:00", "14:00", "16:00"]):
            dock.append((f"DOCK-{facility.split()[0].upper()}-{i+1}", facility, door, f"2026-11-09 {t}", "available", ""))
    c.executemany("INSERT INTO dock_slots VALUES (?,?,?,?,?,?)", dock)
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

CITY_COORDS = {
    "Columbus, OH": (39.96, -82.99), "Chicago, IL": (41.88, -87.63),
    "Cleveland, OH": (41.50, -81.69), "Detroit, MI": (42.33, -83.05),
    "Cincinnati, OH": (39.10, -84.51), "Indianapolis, IN": (39.77, -86.16),
    "Pittsburgh, PA": (40.44, -79.99), "Toledo, OH depot": (41.65, -83.54),
    "Toledo, OH": (41.65, -83.54), "Fort Wayne, IN hub": (41.08, -85.14),
    "Fort Wayne, IN": (41.08, -85.14), "Ann Arbor, MI hub": (42.28, -83.74),
    "Ann Arbor, MI": (42.28, -83.74), "Cincinnati, OH customer": (39.10, -84.51),
}
def haversine_miles(a, b):
    import math as _m
    lat1, lon1 = _m.radians(a[0]), _m.radians(a[1]); lat2, lon2 = _m.radians(b[0]), _m.radians(b[1])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = _m.sin(dlat/2)**2 + _m.cos(lat1)*_m.cos(lat2)*_m.sin(dlon/2)**2
    return 2 * 3959 * _m.asin(_m.sqrt(h))

def _route_cost(order):
    if not order: return 0
    total = float(order[0].get("miles_from_current", 0))
    for prev, cur in zip(order, order[1:]):
        pa, pb = CITY_COORDS.get(prev["place"]), CITY_COORDS.get(cur["place"])
        total += haversine_miles(pa, pb) if pa and pb else abs(float(cur.get("miles_from_current", 0)) - float(prev.get("miles_from_current", 0)))
    return round(total, 1)

def optimise_route(stops):
    """Improved route optimisation (demo heuristic): nearest-first, then
    2-opt improvement using haversine distance between known stop cities
    (fallback: miles_from_current difference). This is NOT an exact TSP
    solver and does NOT yet handle time windows, vehicle capacity, or
    driver hours — those are the next production step (OR-Tools)."""
    if not stops: return {"optimised_order": [], "stops": [], "total_miles_estimate": 0, "method": "nearest-first + 2-opt"}
    ordered = sorted(stops, key=lambda s: (s["miles_from_current"], -s["priority"]))
    best, best_cost = ordered, _route_cost(ordered)
    improved = True
    while improved:
        improved = False
        for i in range(len(best)):
            for j in range(i+1, len(best)+1):
                cand = best[:i] + list(reversed(best[i:j])) + best[j:]
                c = _route_cost(cand)
                if c < best_cost - 0.1:
                    best, best_cost, improved = cand, c, True
    return {"optimised_order": [s["place"] for s in best], "stops": best, "total_miles_estimate": best_cost, "method": "nearest-first + 2-opt"}

def map_data():
    out = []
    for s in all_shipments():
        out.append({"id": s["id"], "origin": s["origin"], "destination": s["destination"],
                    "origin_coords": CITY_COORDS.get(s["origin"]), "destination_coords": CITY_COORDS.get(s["destination"]),
                    "driver": s["driver"], "vehicle": s["vehicle"], "status": s["status"],
                    "ai_status": s["eta"]["status"] if s["eta"] else "delivered",
                    "eta_minutes": s["eta"]["predicted_minutes"] if s["eta"] else None,
                    "delay_reasons": s["eta"]["delay_reasons"] if s["eta"] else []})
    return out

def dispatcher_briefing():
    from collections import Counter
    ships = all_shipments(); a = analytics()
    delayed = [s for s in ships if s["eta"] and s["eta"]["status"] == "delayed"]
    at_risk = [s for s in ships if s["eta"] and s["eta"]["status"] == "at_risk"]
    stale = [s for s in ships if s["eta"] and s["eta"]["gps_stale"]]
    reasons = Counter(r for s in ships if s["eta"] for r in s["eta"]["delay_reasons"] if r != "on schedule")
    actions = []
    if delayed: actions.append(f"Contact customers for {len(delayed)} delayed shipment(s): {', '.join(s['id'] for s in delayed)}.")
    if at_risk: actions.append(f"Watch {len(at_risk)} at-risk shipment(s) and re-check their ETAs before the delivery window.")
    if stale: actions.append(f"Check GPS for {len(stale)} shipment(s) with stale signal before promising a time.")
    if not actions: actions.append("No urgent actions — fleet is on schedule in this demo.")
    return {"total": a["total"], "active": a["active"], "by_status": a["by_status"],
            "delayed": [s["id"] for s in delayed], "at_risk": [s["id"] for s in at_risk],
            "gps_stale": [s["id"] for s in stale], "top_delay_reasons": dict(reasons.most_common(5)),
            "recommended_actions": actions,
            "summary": f"Fleet briefing: {a['active']} active of {a['total']}. Delayed: {len(delayed)}, at-risk: {len(at_risk)}, GPS stale: {len(stale)}. Top reasons: {dict(reasons.most_common(3)) or 'none'}."}

def send_notification(shipment_id, channel, message):
    """Twilio-ready notification sender. If TWILIO_ACCOUNT_SID,
    TWILIO_AUTH_TOKEN, TWILIO_FROM and a destination are set, it really
    sends via Twilio; otherwise it logs only and honestly reports
    sent=False, provider=log_only. Never claim a real send without it."""
    import urllib.request, urllib.parse, base64
    sid, token, frm = os.environ.get("TWILIO_ACCOUNT_SID"), os.environ.get("TWILIO_AUTH_TOKEN"), os.environ.get("TWILIO_FROM")
    to = os.environ.get("NOTIFY_TO")
    if channel == "sms" and sid and token and frm and to:
        try:
            data = urllib.parse.urlencode({"From": frm, "To": to, "Body": message}).encode()
            req = urllib.request.Request(f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json", data=data,
                headers={"Authorization": "Basic " + base64.b64encode(f"{sid}:{token}".encode()).decode()})
            urllib.request.urlopen(req, timeout=15)
            sent, provider = True, "twilio"
        except Exception as e:
            sent, provider, err = False, "twilio_failed", str(e)
            con = sqlite3.connect(DB); con.execute("INSERT INTO notifications (shipment_id, channel, kind, message) VALUES (?,?,?,?)", (shipment_id, channel, "manual_failed", message)); con.commit(); con.close()
            return {"sent": sent, "provider": provider, "error": err}
    else:
        sent, provider = False, "log_only"
    con = sqlite3.connect(DB); con.execute("INSERT INTO notifications (shipment_id, channel, kind, message) VALUES (?,?,?,?)", (shipment_id, channel, "manual", message)); con.commit(); con.close()
    return {"sent": sent, "provider": provider, "note": "Set TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM and NOTIFY_TO to send real SMS." if provider == "log_only" else "Sent via Twilio."}

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

def list_dock_slots(status=None, facility=None):
    con = sqlite3.connect(DB); con.row_factory = sqlite3.Row
    q, args = "SELECT * FROM dock_slots ORDER BY slot_time", ()
    if status: q, args = "SELECT * FROM dock_slots WHERE status=? ORDER BY slot_time", (status,)
    rows = [dict(r) for r in con.execute(q, args)]; con.close()
    if facility: rows = [r for r in rows if r["facility"] == facility]
    return rows

def book_dock_slot(slot_id, shipment_id):
    """Book a dock slot. A booked slot cuts that shipment's dwell to
    15 min (from its seeded dwell), so its ETA improves — the point of
    dock scheduling. Returns dict with ok / error."""
    con = sqlite3.connect(DB); con.row_factory = sqlite3.Row
    slot = con.execute("SELECT * FROM dock_slots WHERE id=?", (slot_id,)).fetchone()
    if not slot: con.close(); return {"ok": False, "error": f"slot {slot_id} not found"}
    if slot["status"] != "available": con.close(); return {"ok": False, "error": f"slot {slot_id} is already {slot['status']}"}
    ship = con.execute("SELECT * FROM shipments WHERE id=?", (shipment_id,)).fetchone()
    if not ship: con.close(); return {"ok": False, "error": f"shipment {shipment_id} not found"}
    con.execute("UPDATE dock_slots SET status='booked', shipment_id=? WHERE id=?", (shipment_id, slot_id))
    con.execute("UPDATE shipments SET dwell_remaining_min=15 WHERE id=?", (shipment_id,))
    con.commit(); con.close()
    return {"ok": True, "slot_id": slot_id, "shipment_id": shipment_id, "facility": slot["facility"], "slot_time": slot["slot_time"], "dwell_remaining_min": 15}

def get_dock_booking(shipment_id):
    con = sqlite3.connect(DB); con.row_factory = sqlite3.Row
    r = con.execute("SELECT * FROM dock_slots WHERE shipment_id=?", (shipment_id,)).fetchone()
    con.close(); return dict(r) if r else None

def dwell_stats():
    ships = all_shipments()
    booked = [s for s in ships if get_dock_booking(s["id"])]
    avg_all = round(sum(s["dwell_remaining_min"] for s in ships) / len(ships), 1) if ships else 0
    return {"total_slots": len(list_dock_slots()), "available_slots": len(list_dock_slots(status="available")),
            "booked_slots": len(list_dock_slots(status="booked")), "avg_dwell_remaining_min": avg_all,
            "booked_shipments": [s["id"] for s in booked]}

# ---------- DEMAND FORECASTING (weekly truck need by lane, seeded history) ----------
# Honest scope: forecasts are a 4-week moving average + trend on SEEDED
# demo history (8 weeks, invented for the demo). They are NOT trained on
# real bookings and must be re-fit on real order history before any
# capacity or hiring decision. Forecast week is the Monday after the
# last seeded week.
DEMAND_WEEKS = ["2026-09-14", "2026-09-21", "2026-09-28", "2026-10-05",
                "2026-10-12", "2026-10-19", "2026-10-26", "2026-11-02"]
DEMAND_FORECAST_WEEK = "2026-11-09"
DEMAND_SEED = {
    "Columbus, OH → Chicago, IL":     [12, 13, 12, 14, 13, 15, 14, 16],
    "Columbus, OH → Cleveland, OH":   [8, 9, 8, 9, 10, 9, 10, 10],
    "Chicago, IL → Detroit, MI":      [10, 10, 11, 10, 12, 11, 12, 13],
    "Columbus, OH → Cincinnati, OH":  [6, 7, 6, 7, 7, 8, 7, 8],
    "Indianapolis, IN → Columbus, OH": [5, 5, 6, 5, 6, 6, 7, 6],
    "Chicago, IL → Columbus, OH":     [9, 9, 10, 9, 10, 11, 10, 11],
    "Detroit, MI → Cleveland, OH":    [4, 4, 5, 4, 5, 5, 5, 6],
    "Columbus, OH → Pittsburgh, PA":  [7, 7, 8, 7, 8, 9, 8, 9],
}

def seed_demand_history(con):
    c = con.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS demand_history
        (lane TEXT, week_start TEXT, trucks INTEGER)""")
    c.execute("DELETE FROM demand_history")
    for lane, weeks in DEMAND_SEED.items():
        for wk, n in zip(DEMAND_WEEKS, weeks):
            c.execute("INSERT INTO demand_history VALUES (?,?,?)", (lane, wk, n))

def demand_history(lane=None):
    con = sqlite3.connect(DB); con.row_factory = sqlite3.Row
    q = "SELECT lane, week_start, trucks FROM demand_history ORDER BY lane, week_start"
    args = ()
    if lane:
        q = "SELECT lane, week_start, trucks FROM demand_history WHERE lane=? ORDER BY week_start"
        args = (lane,)
    rows = [dict(r) for r in con.execute(q, args)]
    con.close()
    return rows

def forecast_demand(lane=None):
    """Forecast next week's truck need per lane: 4-week moving average
    plus the recent trend (last week minus first of the last 4, per week),
    rounded up to whole trucks. Confidence falls as week-to-week
    variability rises. Seeded demo history only — see DEMAND_SEED."""
    rows = demand_history(lane)
    by_lane = {}
    for r in rows:
        by_lane.setdefault(r["lane"], []).append(r["trucks"])
    out = []
    for lane_name, weeks in sorted(by_lane.items()):
        if len(weeks) < 4:
            continue
        last4 = weeks[-4:]
        avg = sum(last4) / len(last4)
        trend = (last4[-1] - last4[0]) / 3.0
        forecast = max(1, math.ceil(avg + trend))
        mean = avg
        var = sum((x - mean) ** 2 for x in last4) / len(last4)
        cv = (math.sqrt(var) / mean) if mean else 0
        confidence = round(clamp(0.95 - cv, 0.5, 0.95), 2)
        direction = "up" if trend > 0.5 else ("down" if trend < -0.5 else "flat")
        out.append({
            "lane": lane_name,
            "forecast_week_start": DEMAND_FORECAST_WEEK,
            "history_weeks": len(weeks),
            "history": weeks,
            "avg_last_4_weeks": round(avg, 1),
            "trend_per_week": round(trend, 2),
            "forecast_trucks_next_week": forecast,
            "confidence": confidence,
            "confidence_label": "high" if cv < 0.1 else ("medium" if cv < 0.2 else "low"),
            "direction": direction,
            "recommendation": f"Plan {forecast} truck(s) on {lane_name} for the week of {DEMAND_FORECAST_WEEK} ({direction} vs recent average {round(avg, 1)}).",
        })
    total = sum(f["forecast_trucks_next_week"] for f in out)
    return {"forecast_week_start": DEMAND_FORECAST_WEEK, "total_trucks_next_week": total,
            "lanes": out, "method": "4-week moving average + trend, on seeded demo history — not real bookings",
            "note": "Demo forecast from seeded history only. Re-fit on real order history before capacity decisions."}

# ---------- DRIVER SAFETY SCORE (harsh braking / speeding / idle proxy) ----------
# Honest scope: scores are computed from SEEDED demo telematics-style
# event counts (last 30 days, invented for the demo). They are NOT from a
# real telematics feed or dashcam — a production version would ingest
# real harsh-braking / speeding / idle events per driver and calibrate
# the weights on real incident data.
SAFETY_PERIOD_DAYS = 30
SAFETY_SEED = {
    # driver: (miles_driven, harsh_braking_events, speeding_events, long_idle_events)
    "A. Kumar":  (2400, 3, 2, 4),
    "M. Lee":    (1800, 5, 4, 6),
    "S. Patel":  (2100, 12, 9, 10),
    "J. Smith":  (1500, 4, 3, 3),
    "R. Davis":  (2600, 6, 5, 8),
    "T. Nguyen": (1200, 12, 9, 14),
    "K. Jones":  (1900, 16, 12, 9),
    "L. Brown":  (900, 14, 11, 15),
}
# Points deducted per event per 100 miles driven.
SAFETY_WEIGHTS = {"harsh_braking": 15.0, "speeding": 10.0, "long_idle": 5.0}

def seed_safety_events(con):
    c = con.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS safety_events
        (driver TEXT, miles_driven REAL, harsh_braking INTEGER,
         speeding INTEGER, long_idle INTEGER)""")
    c.execute("DELETE FROM safety_events")
    for driver, (miles, harsh, speeding, idle) in SAFETY_SEED.items():
        c.execute("INSERT INTO safety_events VALUES (?,?,?,?,?)",
                  (driver, miles, harsh, speeding, idle))

def safety_events(driver=None):
    con = sqlite3.connect(DB); con.row_factory = sqlite3.Row
    q = "SELECT * FROM safety_events ORDER BY driver"
    args = ()
    if driver:
        q = "SELECT * FROM safety_events WHERE driver=? ORDER BY driver"
        args = (driver,)
    rows = [dict(r) for r in con.execute(q, args)]
    con.close()
    return rows

def safety_band(score):
    if score >= 90: return "Excellent"
    if score >= 75: return "Good"
    if score >= 60: return "Fair"
    return "At risk"

def driver_safety_scores(driver=None):
    """Per-driver safety score 0-100 from seeded event counts.
    Score = 100 - weighted event rates per 100 miles. Higher is safer.
    Seeded demo data only — see SAFETY_SEED."""
    out = []
    for r in safety_events(driver):
        miles = float(r["miles_driven"]) or 1
        per100 = {k: r[k] / miles * 100 for k in ("harsh_braking", "speeding", "long_idle")}
        deductions = {k: round(SAFETY_WEIGHTS[k] * per100[k], 2) for k in per100}
        score = round(clamp(100 - sum(deductions.values()), 0, 100), 1)
        worst = max(deductions, key=deductions.get)
        coaching = {
            "harsh_braking": "Coach smooth braking: increase following distance and brake early.",
            "speeding": "Coach speed compliance: watch speed limits on highway stretches.",
            "long_idle": "Coach idle reduction: switch off during long waits at docks.",
        }[worst]
        out.append({
            "driver": r["driver"],
            "period_days": SAFETY_PERIOD_DAYS,
            "miles_driven": r["miles_driven"],
            "harsh_braking_events": r["harsh_braking"],
            "speeding_events": r["speeding"],
            "long_idle_events": r["long_idle"],
            "harsh_braking_per_100mi": round(per100["harsh_braking"], 2),
            "speeding_per_100mi": round(per100["speeding"], 2),
            "long_idle_per_100mi": round(per100["long_idle"], 2),
            "deductions": deductions,
            "safety_score": score,
            "band": safety_band(score),
            "top_risk_factor": worst,
            "recommendation": coaching if score < 90 else "Keep it up — no coaching needed this period.",
        })
    out.sort(key=lambda x: -x["safety_score"])
    avg = round(sum(d["safety_score"] for d in out) / len(out), 1) if out else 0
    return {"period_days": SAFETY_PERIOD_DAYS,
            "fleet_average_score": avg,
            "drivers": out,
            "method": "100 - 15*harsh + 10*speeding + 5*idle events per 100 miles, on seeded demo event counts — not real telematics",
            "note": "Demo safety scores from seeded event counts only. Connect a real telematics feed before using scores for coaching or insurance decisions."}

# ---------- FUEL, TOLL & COST PER TRIP (seeded demo rates) ----------
# Honest scope: costs are estimates from SEEDED demo assumptions, NOT
# real fuel-card, toll-transponder or payroll data. Diesel price, MPG
# per vehicle, flat toll per lane and the driver hourly rate are demo
# inputs dated 2026-11-12. Trip miles are a haversine straight-line
# estimate between origin and destination cities, not road miles.
# A production version would ingest real fuel-card transactions,
# toll bills and driver pay, and use routed road miles.
DIESEL_PRICE_PER_GAL = 3.85   # USD/gal, seeded demo rate, 2026-11-12
DRIVER_HOURLY_RATE = 28.00    # USD/hour, seeded demo rate
VEHICLE_MPG = {  # seeded demo fuel economy per vehicle
    "Truck-02": 6.5, "Truck-03": 7.0, "Truck-04": 6.2, "Truck-05": 7.2,
    "Truck-07": 6.8, "Truck-08": 6.5, "Truck-09": 7.0, "Truck-11": 6.0,
}
DEFAULT_MPG = 6.5
LANE_TOLLS = {  # seeded flat toll per lane (USD), demo assumption
    "Columbus, OH → Chicago, IL": 28.50,
    "Columbus, OH → Cleveland, OH": 6.25,
    "Chicago, IL → Detroit, MI": 18.75,
    "Columbus, OH → Cincinnati, OH": 4.50,
    "Indianapolis, IN → Columbus, OH": 9.80,
    "Chicago, IL → Columbus, OH": 28.50,
    "Detroit, MI → Cleveland, OH": 11.40,
    "Columbus, OH → Pittsburgh, PA": 14.20,
}
TOLL_FALLBACK_PER_MILE = 0.12  # USD/mile when a lane has no seeded toll

def trip_miles(shipment):
    """Full-trip distance estimate: haversine miles origin → destination.
    Straight-line estimate, not road miles — see module note above."""
    a = CITY_COORDS.get(shipment["origin"]); b = CITY_COORDS.get(shipment["destination"])
    if not a or not b:
        return round(float(shipment["remaining_miles"] or 0), 1)
    return round(haversine_miles(a, b), 1)

def trip_cost(shipment):
    """Estimated cost for one shipment: fuel + toll + driver time.
    Driver hours come from the AI ETA (predicted minutes) for active
    shipments, or actual minutes for delivered ones."""
    miles = trip_miles(shipment)
    mpg = VEHICLE_MPG.get(shipment["vehicle"], DEFAULT_MPG)
    gallons = round(miles / mpg, 2) if miles else 0
    fuel_cost = round(gallons * DIESEL_PRICE_PER_GAL, 2)
    lane = f"{shipment['origin']} → {shipment['destination']}"
    toll_cost = round(LANE_TOLLS.get(lane, miles * TOLL_FALLBACK_PER_MILE), 2)
    eta = predict_eta(shipment) if shipment["remaining_miles"] > 0 else None
    minutes = eta["predicted_minutes"] if eta else float(shipment.get("actual_minutes") or 0)
    driver_hours = round(minutes / 60, 2)
    driver_cost = round(driver_hours * DRIVER_HOURLY_RATE, 2)
    total = round(fuel_cost + toll_cost + driver_cost, 2)
    return {
        "shipment_id": shipment["id"],
        "origin": shipment["origin"], "destination": shipment["destination"],
        "driver": shipment["driver"], "vehicle": shipment["vehicle"],
        "status": shipment["status"],
        "trip_miles_estimate": miles,
        "mpg": mpg, "diesel_price_per_gal": DIESEL_PRICE_PER_GAL,
        "fuel_gallons": gallons, "fuel_cost_usd": fuel_cost,
        "toll_cost_usd": toll_cost,
        "driver_hours": driver_hours, "driver_rate_per_hour": DRIVER_HOURLY_RATE,
        "driver_cost_usd": driver_cost,
        "total_cost_usd": total,
        "cost_per_mile_usd": round(total / miles, 2) if miles else 0,
    }

def fleet_costs(shipment_id=None):
    """Per-shipment cost estimates plus fleet totals. Pass an id for a
    single shipment; otherwise all shipments in the demo fleet."""
    ships = all_shipments()
    if shipment_id:
        ships = [s for s in ships if s["id"] == shipment_id]
    costs = [trip_cost(s) for s in ships]
    totals = {k: round(sum(c[k] for c in costs), 2) for k in
              ("fuel_cost_usd", "toll_cost_usd", "driver_cost_usd", "total_cost_usd")}
    miles = round(sum(c["trip_miles_estimate"] for c in costs), 1)
    most = max(costs, key=lambda c: c["total_cost_usd"]) if costs else None
    return {"shipments": costs,
            "fleet_totals_usd": totals,
            "fleet_trip_miles_estimate": miles,
            "fleet_cost_per_mile_usd": round(totals["total_cost_usd"] / miles, 2) if miles else 0,
            "most_expensive_shipment": most["shipment_id"] if most else None,
            "method": "fuel = miles/MPG x $3.85/gal; toll = seeded flat per lane; driver = ETA hours x $28/hr — seeded demo rates, not real fuel-card/toll/payroll data",
            "note": "Demo cost estimates from seeded rates and straight-line trip miles only. Use real fuel-card, toll and payroll data before quoting customers or paying drivers."}

# ---------- COLD-CHAIN TEMPERATURE ALERTS (seeded reefer sensor log) ----------
# Honest scope: temperatures are SEEDED demo sensor readings (12 readings
# per reefer shipment, 15 min apart, invented for the demo). They are NOT
# from a real reefer telematics / IoT sensor feed — a production version
# would ingest live reefer probe data, calibrate thresholds per cargo,
# and page the dispatcher on a real excursion. Thresholds below are
# demo assumptions for chilled (2-4 C) and frozen (-20 to -16 C) cargo.
COLD_CHAIN_SHIPMENTS = {
    # shipment_id: (cargo, temp_min_c, temp_max_c)
    "TRK-101": ("Chilled produce", 2.0, 4.0),
    "TRK-103": ("Frozen food", -20.0, -16.0),
    "TRK-105": ("Dairy (chilled)", 2.0, 4.0),
    "TRK-107": ("Frozen pharmaceuticals", -20.0, -16.0),
}
COLD_CHAIN_BASE_TIME = "2026-11-12T09:00:00Z"
COLD_CHAIN_READINGS = {
    "TRK-101": [2.1, 2.4, 2.8, 3.1, 3.5, 3.2, 2.9, 3.0, 3.4, 3.1, 2.7, 3.0],
    "TRK-103": [-18.5, -18.2, -17.8, -17.5, -16.9, -15.2, -14.8, -14.1, -13.9, -14.5, -15.8, -16.4],
    "TRK-105": [2.5, 3.0, 3.6, 4.1, 4.3, 3.9, 3.4, 3.2, 2.9, 3.3, 3.8, 3.5],
    "TRK-107": [-19.1, -18.8, -18.4, -19.0, -18.6, -18.9, -19.2, -18.5, -18.7, -19.0, -18.8, -18.6],
}

def seed_temp_readings(con):
    c = con.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS temp_readings
        (shipment_id TEXT, reading_time TEXT, temp_c REAL)""")
    c.execute("DELETE FROM temp_readings")
    base = datetime.fromisoformat(COLD_CHAIN_BASE_TIME.replace("Z", "+00:00"))
    for sid, temps in COLD_CHAIN_READINGS.items():
        for i, t in enumerate(temps):
            ts = (base + timedelta(minutes=15 * i)).isoformat().replace("+00:00", "Z")
            c.execute("INSERT INTO temp_readings VALUES (?,?,?)", (sid, ts, t))

def temp_readings(shipment_id=None):
    con = sqlite3.connect(DB); con.row_factory = sqlite3.Row
    q = "SELECT * FROM temp_readings ORDER BY shipment_id, reading_time"
    args = ()
    if shipment_id:
        q = "SELECT * FROM temp_readings WHERE shipment_id=? ORDER BY reading_time"
        args = (shipment_id,)
    rows = [dict(r) for r in con.execute(q, args)]
    con.close()
    return rows

def _cold_chain_for(sid, readings, ship):
    cargo, tmin, tmax = COLD_CHAIN_SHIPMENTS[sid]
    temps = [r["temp_c"] for r in readings]
    out_flags = [t < tmin or t > tmax for t in temps]
    out_count = sum(out_flags)
    longest, run = 0, 0
    for f in out_flags:
        run = run + 1 if f else 0
        longest = max(longest, run)
    max_dev = round(max([0.0] + [max(t - tmax, tmin - t, 0) for t in temps]), 1)
    current = temps[-1] if temps else None
    in_range_pct = round(100 * (len(temps) - out_count) / len(temps), 1) if temps else 0
    current_dev = round(max(current - tmax, tmin - current, 0), 1) if current is not None else 0
    if longest >= 3 or current_dev > 2.0:
        status = "critical"
        rec = (f"Sustained excursion: {longest} consecutive readings out of band, up to "
               f"{max_dev}°C outside the {tmin}–{tmax}°C band. Check the reefer unit now and "
               f"alert the customer — cargo may be at risk.")
    elif out_count > 0:
        status = "warning"
        rec = ("Brief excursion outside the band — check the reefer unit at the next stop "
               "and watch the next readings.")
    else:
        status = "ok"
        rec = "Temperature in band — no action needed."
    return {
        "shipment_id": sid, "cargo": cargo,
        "origin": ship["origin"] if ship else None,
        "destination": ship["destination"] if ship else None,
        "driver": ship["driver"] if ship else None,
        "vehicle": ship["vehicle"] if ship else None,
        "shipment_status": ship["status"] if ship else None,
        "temp_min_c": tmin, "temp_max_c": tmax,
        "readings": len(temps),
        "latest_reading_time": readings[-1]["reading_time"] if readings else None,
        "current_temp_c": current,
        "min_temp_c": round(min(temps), 1) if temps else None,
        "max_temp_c": round(max(temps), 1) if temps else None,
        "in_range_pct": in_range_pct,
        "out_of_range_count": out_count,
        "longest_excursion_readings": longest,
        "max_deviation_c": max_dev,
        "status": status,
        "recommendation": rec,
    }

def cold_chain_status(shipment_id=None):
    """Per-reefer-shipment temperature status from the seeded sensor log.
    Status: critical if 3+ consecutive readings out of band or the current
    reading is >2°C out of band; warning if any reading is out of band;
    ok otherwise. Seeded demo readings only — see COLD_CHAIN_READINGS."""
    ships = all_shipments()
    by_id = {s["id"]: s for s in ships}
    ids = [shipment_id] if shipment_id else sorted(COLD_CHAIN_SHIPMENTS)
    out = []
    for sid in ids:
        if sid not in COLD_CHAIN_SHIPMENTS:
            continue
        out.append(_cold_chain_for(sid, temp_readings(sid), by_id.get(sid)))
    counts = {"ok": 0, "warning": 0, "critical": 0}
    for s in out:
        counts[s["status"]] += 1
    return {"reefer_shipments": len(out), "ok": counts["ok"], "warning": counts["warning"],
            "critical": counts["critical"],
            "alerts": [s for s in out if s["status"] != "ok"],
            "shipments": out,
            "method": "critical if 3+ consecutive readings out of band or current reading >2°C out of band; warning if any reading out of band; else ok — on seeded demo sensor readings",
            "note": "Demo temperature log from seeded readings only (12 readings per reefer shipment, 15 min apart). Connect a real reefer sensor feed before using alerts for cargo decisions."}

def record_temp_reading(shipment_id, temp_c):
    """Log a new (demo) temperature reading for a reefer shipment and
    return its updated cold-chain status. Returns ok=False for a
    non-reefer or unknown shipment."""
    if shipment_id not in COLD_CHAIN_SHIPMENTS:
        return {"ok": False, "error": f"{shipment_id} is not a refrigerated (reefer) shipment in this demo"}
    con = sqlite3.connect(DB)
    con.execute("INSERT INTO temp_readings VALUES (?,?,?)",
                (shipment_id, datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"), float(temp_c)))
    con.commit(); con.close()
    st = cold_chain_status(shipment_id)
    return {"ok": True, "shipment": st["shipments"][0] if st["shipments"] else None}

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
            "pod": get_pod(shipment_id), "notifications": list_notifications(shipment_id),
            "dock_booking": get_dock_booking(shipment_id),
            "cold_chain": cold_chain_status(shipment_id)["shipments"][0] if shipment_id in COLD_CHAIN_SHIPMENTS else None}

# ---------- LIVE CHATBOT (dashboard AI assistant, rule-based demo) ----------
# Honest scope: this assistant answers from live shipment/ETA data in this
# demo database. It is NOT an external LLM and it does NOT send real SMS,
# email, or support tickets. A production version would plug an LLM API
# here, with the same shipment-data tools below.
import re
def chat_reply(message):
    msg = (message or "").strip()
    low = msg.lower()
    ships = all_shipments()
    m = re.search(r"trk-\d+", low)
    if m:
        sid = m.group(0).upper()
        s = next((x for x in ships if x["id"] == sid), None)
        if not s:
            return {"reply": f"I could not find {sid} in the demo fleet. Try TRK-101 to TRK-108.", "suggestions": ["Which trucks are delayed?", "What is TRK-101 ETA?", "How do I record proof of delivery?"]}
        if not s["eta"]:
            return {"reply": f"{sid} is delivered: {s['origin']} → {s['destination']}, driver {s['driver']}.", "shipment_id": sid}
        e = s["eta"]
        return {"reply": f"{sid}: {s['origin']} → {s['destination']}, driver {s['driver']} / {s['vehicle']}. Status: {s['status']}, AI status: {e['status']}. ETA in about {e['predicted_minutes']} min (window {e['window_minutes'][0]}–{e['window_minutes'][1]} min), confidence {e['confidence']}, delay probability {e['delay_probability']}. Reasons: {', '.join(e['delay_reasons'])}.", "shipment_id": sid}
    if any(k in low for k in ("delay", "late", "at risk", "at-risk", "risk")):
        bad = [s for s in ships if s["eta"] and s["eta"]["status"] in ("delayed", "at_risk")]
        if not bad:
            return {"reply": "Good news: no trucks are currently delayed or at risk in the demo fleet.", "suggestions": ["Show all shipments", "What is my on-time rate?"]}
        lines = "; ".join(f"{s['id']} ({s['eta']['status']}, {s['eta']['predicted_minutes']} min, {', '.join(s['eta']['delay_reasons'])})" for s in bad)
        return {"reply": f"Trucks needing attention: {lines}. Open their detail page to re-route, notify the customer, or record proof of delivery.", "suggestions": ["What is TRK-101 ETA?", "How do I record proof of delivery?"]}
    if "on-time" in low or "on time" in low or "accuracy" in low or "mae" in low:
        a = analytics()
        return {"reply": f"Demo fleet: {a['total']} shipments, {a['active']} active. By AI status: {a['by_status']}. Model error on simulated demo data: {a['mae_model_min']} min vs baseline {a['mae_baseline_min']} min. This is demo data only — real accuracy must be measured on a pilot fleet.", "suggestions": ["Which trucks are delayed?", "Show fleet analytics"]}
    if "forecast" in low or "demand" in low or "next week" in low:
        f = forecast_demand()
        top = sorted(f["lanes"], key=lambda x: -x["forecast_trucks_next_week"])[:3]
        ex = "; ".join(f"{x['lane']}: {x['forecast_trucks_next_week']} trucks ({x['direction']}, confidence {x['confidence']})" for x in top)
        return {"reply": f"Demand forecast for the week of {f['forecast_week_start']}: {f['total_trucks_next_week']} trucks total across {len(f['lanes'])} lanes. Top lanes: {ex}. This is a demo forecast from seeded history, not real bookings — open /forecast for the full breakdown.", "suggestions": ["Which trucks are delayed?", "What is TRK-101 ETA?"]}
    if "dock" in low or "dwell" in low:
        d = dwell_stats()
        avail = list_dock_slots(status="available")[:3]
        ex = ", ".join(f"{s['id']} {s['facility']} {s['slot_time']}" for s in avail)
        return {"reply": f"Dock scheduling: {d['available_slots']} of {d['total_slots']} slots available, {d['booked_slots']} booked. Average dwell remaining is {d['avg_dwell_remaining_min']} min. Booking a slot cuts that shipment's dwell to 15 min and improves its ETA. Examples: {ex}. Open /dock to book.", "suggestions": ["Which trucks are delayed?", "What is TRK-101 ETA?"]}
    if "pod" in low or "proof of delivery" in low or "deliver" in low and "proof" in low:
        return {"reply": "To record proof of delivery: open a shipment detail page, fill method (signature / photo / OTP), signed-by name and OTP, then submit. It is stored and the shipment becomes delivered. Try TRK-106 — it already has a seeded POD.", "suggestions": ["What is TRK-106 status?", "Show all shipments"]}
    if "route" in low or "optim" in low:
        return {"reply": "Route optimisation in this demo is a nearest-first stub, not a full TSP solver: open /shipment?id=TRK-101 to see its optimised stop order. A production version would add time windows, vehicle capacity, and driver hours.", "suggestions": ["What is TRK-101 ETA?", "Which trucks are delayed?"]}
    if "fuel" in low or "toll" in low or "trip cost" in low or "cost per trip" in low or "cost of" in low or "how much does" in low and "cost" in low:
        c = fleet_costs()
        t = c["fleet_totals_usd"]
        ex = "; ".join(f"{x['shipment_id']}: ${x['total_cost_usd']} (${x['cost_per_mile_usd']}/mi)" for x in sorted(c["shipments"], key=lambda x: -x["total_cost_usd"])[:3])
        return {"reply": f"Trip cost (demo estimates from seeded rates: diesel ${DIESEL_PRICE_PER_GAL}/gal, driver ${DRIVER_HOURLY_RATE}/hr, seeded tolls per lane): fleet total ${t['total_cost_usd']} across {len(c['shipments'])} shipments — fuel ${t['fuel_cost_usd']}, tolls ${t['toll_cost_usd']}, driver time ${t['driver_cost_usd']}, {c['fleet_cost_per_mile_usd']}/mile. Most expensive: {ex}. These are estimates, not real fuel-card or toll data — open /cost for the full breakdown.", "suggestions": ["Which trucks are delayed?", "What is TRK-101 ETA?", "What is my on-time rate?"]}
    if "price" in low or "pricing" in low or "cost" in low:
        return {"reply": "Pricing is intentionally not locked in this demo — test it after a pilot. The pricing page shows Starter (up to 10 vehicles), Growth (up to 50), and Scale (unlimited) tiers.", "suggestions": ["How do I use the dashboard?", "Talk to support"]}
    if "support" in low or "human" in low or "contact" in low or "help" in low or low in ("hi", "hello", "hey"):
        return {"reply": "Hi, I'm the Logistics AI assistant in this dashboard. I can help with shipment status, ETAs, delays, proof of delivery, routes, fleet analytics, and how to use this product. For a real human in production, this would open a support ticket — in this demo, tell me the shipment ID or issue and I'll check the live data. Try: 'Which trucks are delayed?' or 'What is TRK-101 ETA?'", "suggestions": ["Which trucks are delayed?", "What is TRK-101 ETA?", "How do I record proof of delivery?", "What is my on-time rate?"]}
    if "how" in low or "use" in low or "dashboard" in low:
        return {"reply": "Dashboard help: use Search and the status filter (on_time / at_risk / delayed / delivered) to find trucks. Click Detail for ETA, stops, route, POD, and notifications. Use /portal for a customer-only view, /fleet for per-driver analytics, and this chat anytime for a shipment ID.", "suggestions": ["Which trucks are delayed?", "What is TRK-101 ETA?"]}
    if "safety" in low or "safe driving" in low:
        s = driver_safety_scores()
        best, worst = s["drivers"][0], s["drivers"][-1]
        return {"reply": f"Driver safety (last {s['period_days']} days, seeded demo data): fleet average {s['fleet_average_score']}. Best: {best['driver']} at {best['safety_score']} ({best['band']}). Needs coaching: {worst['driver']} at {worst['safety_score']} ({worst['band']}) — {worst['recommendation']} Open /safety for the full table.", "suggestions": ["Which trucks are delayed?", "What is my on-time rate?"]}
    if any(k in low for k in ("cold chain", "cold-chain", "temperature", "temp", "reefer", "frozen", "chilled", "fridge")):
        cc = cold_chain_status()
        crit = [s for s in cc["shipments"] if s["status"] == "critical"]
        warn = [s for s in cc["shipments"] if s["status"] == "warning"]
        if not crit and not warn:
            return {"reply": f"Cold chain looks fine: all {cc['reefer_shipments']} reefer shipments are in their temperature band (demo sensor log). Open /coldchain for the full log.", "suggestions": ["Which trucks are delayed?", "What is TRK-101 ETA?"]}
        lines = "; ".join(f"{s['shipment_id']} ({s['cargo']}, {s['current_temp_c']}°C vs {s['temp_min_c']}–{s['temp_max_c']}°C, {s['status']})" for s in crit + warn)
        return {"reply": f"Cold-chain alerts (demo sensor log): {len(crit)} critical, {len(warn)} warning of {cc['reefer_shipments']} reefer shipments. {lines}. Open /coldchain for the full temperature log and recommendations.", "suggestions": ["Which trucks are delayed?", "What is TRK-101 ETA?"]}
    if "fleet" in low or "driver" in low:
        f = fleet_analytics()
        drivers = ", ".join(f"{k}: {v['shipments']} shipments, {v['delivered']} delivered" for k, v in f["by_driver"].items())
        return {"reply": f"Fleet (demo): {drivers}. Open /fleet for per-driver and per-vehicle error and on-time proxy.", "suggestions": ["Which trucks are delayed?", "What is my on-time rate?"]}
    return {"reply": "I can help with logistics issues in this dashboard: shipment status and ETAs, delays, proof of delivery, routes, fleet analytics, and pricing. Try asking with a shipment ID, for example 'What is TRK-101 ETA?' or 'Which trucks are delayed?'", "suggestions": ["Which trucks are delayed?", "What is TRK-101 ETA?", "How do I record proof of delivery?", "What is my on-time rate?"]}

CHAT_WIDGET = """
<div class='card' id='chatbot'><h3>Live AI Chatbot — ask about any shipment or issue</h3>
<div id='chatlog' style='border:1px solid #ddd;border-radius:8px;padding:12px;min-height:120px;max-height:300px;overflow:auto'></div>
<p><input id='chatinput' style='width:70%' placeholder='Ask: Which trucks are delayed? / What is TRK-101 ETA?'> <button onclick='sendChat()'>Send</button></p>
<p><small>Demo assistant: answers from live demo shipment data. Not an external LLM, not real support.</small></p>
<script>
async function sendChat(){
  const inp=document.getElementById('chatinput'); const log=document.getElementById('chatlog');
  const q=inp.value.trim(); if(!q) return;
  log.innerHTML+='<p><b>You:</b> '+q+'</p>'; inp.value='';
  const r=await fetch('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message:q})});
  const d=await r.json(); log.innerHTML+='<p><b>AI:</b> '+d.reply+'</p>';
  if(d.suggestions){ log.innerHTML+='<p><i>Try: '+d.suggestions.join(' · ')+'</i></p>'; }
  log.scrollTop=log.scrollHeight;
}
document.getElementById('chatinput').addEventListener('keydown',e=>{if(e.key==='Enter') sendChat();});
</script></div>
"""

# ---------- WEB ----------
def page(title, body):
    return f"""<!doctype html><html><head><meta charset='utf-8'>
    <title>{title}</title><style>
    body{{font-family:system-ui,sans-serif;max-width:980px;margin:24px auto;padding:0 16px}}
    table{{border-collapse:collapse;width:100%}} td,th{{border:1px solid #ddd;padding:8px;text-align:left}}
    .card{{border:1px solid #ddd;border-radius:12px;padding:16px;margin:12px 0}}
    a{{color:#0b5fff}} .pill{{padding:2px 8px;border-radius:999px;background:#eef2ff}}
    </style></head><body><h1>{title}</h1>{body}
    <p><a href='/'>Home</a> · <a href='/dashboard'>Dashboard</a> · <a href='/portal'>Customer Portal</a> · <a href='/analytics'>Analytics</a> · <a href='/fleet'>Fleet</a> · <a href='/forecast'>Demand Forecast</a> · <a href='/safety'>Driver Safety</a> · <a href='/cost'>Trip Cost</a> · <a href='/coldchain'>Cold Chain</a> · <a href='/notifications'>Notifications</a> · <a href='/pricing'>Pricing</a> · <a href='/api/shipments'>API JSON</a></p>
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
            <li>Proof of delivery · Route optimisation (nearest-first + 2-opt) · Fleet analytics · Notifications log · Customer portal · Dock scheduling · <a href='/forecast'>Demand forecasting</a> · <a href='/safety'>Driver safety score</a> · <a href='/cost'>Fuel, toll & cost per trip</a> · <a href='/coldchain'>Cold-chain temperature alerts</a></li></ul></div>"""))
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
            self._send(200, page("Dispatcher Dashboard", f"<div>{summary}</div><form method='get' action='/dashboard'>Search: <input name='q' value='{q.get('q',[''])[0]}'> <input type='submit' value='Search'></form><p>{filters}</p><table><tr><th>ID</th><th>Route</th><th>Driver / Vehicle</th><th>Status</th><th>ETA min</th><th>Confidence</th><th>AI status</th><th></th></tr>{rows}</table><p>Showing {len(ships)} shipment(s). Simulated demo data only.</p>{CHAT_WIDGET}"))
        elif u.path == "/shipment":
            d = shipment_detail(q.get("id", ["TRK-101"])[0])
            if not d: return self._send(404, page("Not found", "<p>Shipment not found.</p>"))
            stops = "<br>".join(f"{s['place']} — {s['miles_from_current']} mi (priority {s['priority']})" for s in d["stops"]) or "No multi-stop data"
            route = f"<p>Optimised order ({d['route'].get('method','nearest-first + 2-opt')}, {d['route'].get('total_miles_estimate')} mi est.): {d['route']['optimised_order'] if d['route'] else '—'}</p>" if d["route"] else ""
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
        elif u.path == "/map":
            self._send(200, page("Live Map — Routes & Status", """
            <link rel='stylesheet' href='https://unpkg.com/leaflet@1.9.4/dist/leaflet.css'>
            <div id='map' style='height:520px;border-radius:12px'></div>
            <p>Green = on time, amber = at risk, red = delayed, grey = delivered. Lines are origin → destination routes (demo cities, not live GPS tracks — live GPS needs a real telematics feed).</p>
            <script src='https://unpkg.com/leaflet@1.9.4/dist/leaflet.js'></script>
            <script>fetch('/api/map').then(r=>r.json()).then(data=>{
              const map=L.map('map').setView([41.0,-84.5],6);
              L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:18,attribution:'© OpenStreetMap'}).addTo(map);
              const col={on_time:'green',at_risk:'orange',delayed:'red',delivered:'grey'};
              data.forEach(s=>{ if(!s.origin_coords||!s.destination_coords) return;
                L.marker(s.origin_coords).addTo(map).bindPopup(s.id+' origin: '+s.origin);
                L.marker(s.destination_coords).addTo(map).bindPopup(s.id+' → '+s.destination+'<br>'+s.ai_status+'<br>ETA '+s.eta_minutes+' min');
                L.polyline([s.origin_coords,s.destination_coords],{color:col[s.ai_status]||'blue'}).addTo(map); });
            });</script>"""))
        elif u.path == "/briefing":
            b = dispatcher_briefing()
            acts = "<br>".join(b["recommended_actions"])
            self._send(200, page("AI Dispatcher Briefing", f"<div class='card'><p>{b['summary']}</p><p>Top delay reasons: {b['top_delay_reasons']}</p><h3>Recommended actions</h3><p>{acts}</p><p><a href='/map'>Open live map →</a> · <a href='/chat'>Ask the chatbot →</a></p></div>"))
        elif u.path == "/dock":
            d = dwell_stats()
            rows = "".join(f"<tr><td>{s['id']}</td><td>{s['facility']}</td><td>{s['dock_door']}</td><td>{s['slot_time']}</td><td>{s['status']}</td><td>{s['shipment_id'] or '—'}</td></tr>" for s in list_dock_slots())
            self._send(200, page("Dock Scheduling & Dwell Time", f"<div class='card'><p>Available: {d['available_slots']} / {d['total_slots']} · Booked: {d['booked_slots']} · Avg dwell remaining: {d['avg_dwell_remaining_min']} min</p><p>Booking a slot cuts that shipment's dwell to 15 min and improves its ETA.</p><p>Book: <input id='slot' placeholder='DOCK-COLUMBUS-1'> <input id='ship' placeholder='TRK-101'> <button onclick=\"fetch('/api/dock/book',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{slot_id:document.getElementById('slot').value,shipment_id:document.getElementById('ship').value}})}}).then(r=>r.json()).then(x=>alert(JSON.stringify(x))).then(()=>location.reload())\">Book slot</button></p></div><table><tr><th>Slot</th><th>Facility</th><th>Door</th><th>Time</th><th>Status</th><th>Shipment</th></tr>{rows}</table>"))
        elif u.path == "/forecast":
            f = forecast_demand()
            rows = "".join(f"<tr><td>{x['lane']}</td><td>{', '.join(str(v) for v in x['history'])}</td><td>{x['avg_last_4_weeks']}</td><td>{x['trend_per_week']:+.2f}</td><td><b>{x['forecast_trucks_next_week']}</b></td><td>{x['confidence']} ({x['confidence_label']})</td><td>{x['direction']}</td></tr>" for x in f["lanes"])
            recs = "<br>".join(x["recommendation"] for x in f["lanes"])
            self._send(200, page("Demand Forecast — Weekly Truck Need by Lane", f"<div class='card'><p>Forecast week starting <b>{f['forecast_week_start']}</b> · Total trucks needed: <b>{f['total_trucks_next_week']}</b> across {len(f['lanes'])} lanes</p><p>Method: {f['method']}.</p><p><small>{f['note']}</small></p></div><table><tr><th>Lane</th><th>History (trucks/week, 8 wks)</th><th>Avg last 4 wks</th><th>Trend / wk</th><th>Forecast trucks</th><th>Confidence</th><th>Direction</th></tr>{rows}</table><div class='card'><h3>Recommendations</h3><p>{recs}</p></div>"))
        elif u.path == "/safety":
            s = driver_safety_scores()
            rows = "".join(f"<tr><td>{i+1}</td><td>{d['driver']}</td><td>{d['miles_driven']}</td><td>{d['harsh_braking_events']} ({d['harsh_braking_per_100mi']}/100mi)</td><td>{d['speeding_events']} ({d['speeding_per_100mi']}/100mi)</td><td>{d['long_idle_events']} ({d['long_idle_per_100mi']}/100mi)</td><td><b>{d['safety_score']}</b></td><td>{d['band']}</td><td>{d['top_risk_factor']}</td><td>{d['recommendation']}</td></tr>" for i, d in enumerate(s["drivers"]))
            at_risk = [d for d in s["drivers"] if d["band"] == "At risk"]
            warn = f"<p><b>Needs coaching:</b> {', '.join(d['driver'] for d in at_risk)}.</p>" if at_risk else "<p>No driver is currently At risk.</p>"
            self._send(200, page("Driver Safety Score", f"<div class='card'><p>Last {s['period_days']} days (seeded demo event counts) · Fleet average score: <b>{s['fleet_average_score']}</b></p><p>Method: {s['method']}.</p><p><small>{s['note']}</small></p>{warn}</div><table><tr><th>#</th><th>Driver</th><th>Miles</th><th>Harsh braking</th><th>Speeding</th><th>Long idle</th><th>Score</th><th>Band</th><th>Top risk</th><th>Recommendation</th></tr>{rows}</table>"))
        elif u.path == "/cost":
            c = fleet_costs()
            t = c["fleet_totals_usd"]
            rows = "".join(f"<tr><td>{x['shipment_id']}</td><td>{x['origin']} → {x['destination']}</td><td>{x['driver']} / {x['vehicle']}</td><td>{x['trip_miles_estimate']}</td><td>{x['fuel_gallons']} gal (${x['fuel_cost_usd']})</td><td>${x['toll_cost_usd']}</td><td>{x['driver_hours']} h (${x['driver_cost_usd']})</td><td><b>${x['total_cost_usd']}</b></td><td>${x['cost_per_mile_usd']}</td></tr>" for x in c["shipments"])
            self._send(200, page("Fuel, Toll & Cost per Trip", f"<div class='card'><p>Fleet totals (demo estimates): <b>${t['total_cost_usd']}</b> across {len(c['shipments'])} shipments · {c['fleet_trip_miles_estimate']} trip miles · <b>${c['fleet_cost_per_mile_usd']}/mile</b></p><p>Fuel ${t['fuel_cost_usd']} · Tolls ${t['toll_cost_usd']} · Driver time ${t['driver_cost_usd']} · Most expensive: {c['most_expensive_shipment']}</p><p>Method: {c['method']}.</p><p><small>{c['note']}</small></p></div><table><tr><th>ID</th><th>Route</th><th>Driver / Vehicle</th><th>Trip miles (est.)</th><th>Fuel</th><th>Toll</th><th>Driver time</th><th>Total</th><th>$/mile</th></tr>{rows}</table>"))
        elif u.path == "/coldchain":
            cc = cold_chain_status()
            rows = "".join(f"<tr><td>{s['shipment_id']}</td><td>{s['cargo']}</td><td>{s['origin']} → {s['destination']}</td><td>{s['temp_min_c']}–{s['temp_max_c']} °C</td><td>{s['current_temp_c']} °C</td><td>{s['min_temp_c']}–{s['max_temp_c']} °C</td><td>{s['in_range_pct']}%</td><td>{s['out_of_range_count']}</td><td>{s['longest_excursion_readings']}</td><td><b>{s['status']}</b></td><td>{s['recommendation']}</td></tr>" for s in cc["shipments"])
            self._send(200, page("Cold-Chain Temperature Alerts", f"<div class='card'><p>Reefer shipments: <b>{cc['reefer_shipments']}</b> · In range: {cc['ok']} · Warning: {cc['warning']} · Critical: <b>{cc['critical']}</b></p><p>Method: {cc['method']}.</p><p><small>{cc['note']}</small></p><p>Log a reading (demo): <input id='csid' placeholder='TRK-101'> <input id='ctemp' placeholder='3.5'> <button onclick=\"fetch('/api/coldchain/reading',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{shipment_id:document.getElementById('csid').value,temp_c:parseFloat(document.getElementById('ctemp').value)}})}}).then(r=>r.json()).then(x=>alert(JSON.stringify(x))).then(()=>location.reload())\">Log reading</button></p></div><table><tr><th>ID</th><th>Cargo</th><th>Route</th><th>Band °C</th><th>Current °C</th><th>Min–Max °C</th><th>In range</th><th>Out of range</th><th>Longest excursion</th><th>Status</th><th>Recommendation</th></tr>{rows}</table>"))
        elif u.path == "/chat":
            self._send(200, page("Live AI Chatbot", CHAT_WIDGET + "<p>Ask about any shipment, delay, ETA, POD, route, or fleet issue. The bot answers from live demo data.</p>"))
        elif u.path == "/mobile":
            self._send(200, page("Mobile App", "<p>Mobile web app: open this SaaS on iOS or Android in a browser — the dashboard, tracking, and chatbot are responsive. Native iOS (SwiftUI) and Android (Kotlin) skeletons are in mobile/ios/ and mobile/android/ in the repo, ready to open in Xcode / Android Studio and point at this API.</p><p><a href='/dashboard'>Open dashboard →</a> · <a href='/chat'>Open chatbot →</a></p>"))
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
        elif u.path == "/api/map":
            self._send(200, json.dumps(map_data(), indent=2), "application/json")
        elif u.path == "/api/briefing":
            self._send(200, json.dumps(dispatcher_briefing(), indent=2), "application/json")
        elif u.path == "/api/dock":
            self._send(200, json.dumps({"slots": list_dock_slots(), "stats": dwell_stats()}, indent=2), "application/json")
        elif u.path == "/api/forecast":
            lane = q.get("lane", [None])[0]
            self._send(200, json.dumps(forecast_demand(lane), indent=2), "application/json")
        elif u.path == "/api/safety":
            drv = q.get("driver", [None])[0]
            self._send(200, json.dumps(driver_safety_scores(drv), indent=2), "application/json")
        elif u.path == "/api/cost":
            sid = q.get("id", [None])[0]
            self._send(200, json.dumps(fleet_costs(sid), indent=2), "application/json")
        elif u.path == "/api/coldchain":
            sid = q.get("id", [None])[0]
            self._send(200, json.dumps(cold_chain_status(sid), indent=2), "application/json")
        else:
            self._send(404, page("Not found", "<p>Try /dashboard</p>"))
    def do_POST(self):
        if self.path == "/api/dock/book":
            n = int(self.headers.get("Content-Length", 0)); data = json.loads(self.rfile.read(n) or b"{}")
            self._send(200, json.dumps(book_dock_slot(data.get("slot_id", ""), data.get("shipment_id", "")), indent=2), "application/json")
        elif self.path == "/api/notify":
            n = int(self.headers.get("Content-Length", 0)); data = json.loads(self.rfile.read(n) or b"{}")
            r = send_notification(data.get("id", "TRK-101"), data.get("channel", "sms"), data.get("message", "Update on your delivery."))
            self._send(200, json.dumps(r, indent=2), "application/json")
        elif self.path == "/api/coldchain/reading":
            n = int(self.headers.get("Content-Length", 0)); data = json.loads(self.rfile.read(n) or b"{}")
            try:
                r = record_temp_reading(data.get("shipment_id", ""), float(data.get("temp_c")))
            except (TypeError, ValueError):
                r = {"ok": False, "error": "temp_c must be a number"}
            self._send(200, json.dumps(r, indent=2), "application/json")
        elif self.path == "/api/chat":
            n = int(self.headers.get("Content-Length", 0)); data = json.loads(self.rfile.read(n) or b"{}")
            self._send(200, json.dumps(chat_reply(data.get("message", "")), indent=2), "application/json")
        elif self.path == "/api/pod":
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
    print("LAN: also reachable at http://<your-Mac-LAN-IP>:8000/ for a phone on the same Wi-Fi.")
    # 0.0.0.0 = LAN-reachable (same Wi-Fi only, not the public internet).
    # For phone-only local use, 127.0.0.1 would block the phone, so use 0.0.0.0.
    HTTPServer(("0.0.0.0", 8000), H).serve_forever()
