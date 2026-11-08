"""Tests for the SaaS ETA model. Run: python3 test_saas.py"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from app import predict_eta, optimise_route, record_pod, get_pod, fleet_analytics, list_notifications, init_db, shipment_detail, chat_reply, map_data, dispatcher_briefing, send_notification, list_dock_slots, book_dock_slot, dwell_stats

def base(**kw):
    d = {"id": "TRK-TEST", "remaining_miles": 100, "speed_mph": 55,
         "traffic_factor": 1.0, "weather_factor": 1.0, "lane_factor": 1.0,
         "driver_factor": 1.0, "dwell_remaining_min": 0, "gps_age_min": 1,
         "scheduled_remaining_min": 110}
    d.update(kw); return d

def test_window_and_confidence():
    p = predict_eta(base())
    assert p["window_minutes"][0] < p["predicted_minutes"] < p["window_minutes"][1]
    assert 0.45 <= p["confidence"] <= 0.95
    print("window/confidence OK", p["window_minutes"], p["confidence"])

def test_traffic_slows_eta():
    a = predict_eta(base()); b = predict_eta(base(traffic_factor=1.5))
    assert b["predicted_minutes"] > a["predicted_minutes"]
    assert "traffic" in b["delay_reasons"]
    print("traffic OK", a["predicted_minutes"], "->", b["predicted_minutes"])

def test_stale_gps_lowers_confidence():
    a = predict_eta(base(gps_age_min=1)); b = predict_eta(base(gps_age_min=30))
    assert b["confidence"] < a["confidence"] and b["gps_stale"] is True
    print("stale GPS OK", a["confidence"], "->", b["confidence"])

def test_delay_flag():
    p = predict_eta(base(scheduled_remaining_min=60, traffic_factor=1.6, dwell_remaining_min=60))
    assert p["status"] in ("at_risk", "delayed") and p["delay_probability"] > 0.45
    print("delay flag OK", p["status"], p["delay_probability"])

def test_route_optimisation():
    r = optimise_route([{"place": "B", "miles_from_current": 130, "priority": 1}, {"place": "A", "miles_from_current": 60, "priority": 2}])
    assert r["optimised_order"] == ["A", "B"] and r["method"] == "nearest-first + 2-opt"
    r2 = optimise_route([{"place": "Toledo, OH depot", "miles_from_current": 60, "priority": 2}, {"place": "Fort Wayne, IN hub", "miles_from_current": 130, "priority": 1}])
    assert r2["optimised_order"][0] == "Toledo, OH depot" and r2["total_miles_estimate"] > 0
    print("route optimisation 2-opt OK", r["optimised_order"], r2["total_miles_estimate"])

def test_map_briefing_notify():
    init_db()
    m = map_data()
    assert len(m) == 8 and m[0]["destination_coords"] is not None
    b = dispatcher_briefing()
    assert b["delayed"] and b["recommended_actions"] and "Fleet briefing" in b["summary"]
    n = send_notification("TRK-101", "sms", "Test update")
    assert n["provider"] == "log_only" and n["sent"] is False  # no Twilio env in test
    print("map + briefing + notify OK", len(m), b["delayed"], n["provider"])

def test_pod_and_detail():
    init_db()
    pod = record_pod("TRK-104", "otp", "J. Smith", "123456", "")
    assert get_pod("TRK-104")["otp"] == "123456"
    init_db()  # reset seed so smoke tests are deterministic
    d = shipment_detail("TRK-101")
    assert d and d["route"] and d["route"]["optimised_order"][0] == "Toledo, OH depot"
    print("POD + detail OK", d["route"]["optimised_order"])

def test_notifications_and_fleet():
    init_db()
    assert len(list_notifications()) >= 1
    f = fleet_analytics()
    assert "A. Kumar" in f["by_driver"] and "Truck-07" in f["by_vehicle"]
    print("notifications + fleet OK", len(list_notifications()), "notifications")

def test_chatbot():
    init_db()
    r = chat_reply("What is TRK-101 ETA?")
    assert "TRK-101" in r["reply"] and r["shipment_id"] == "TRK-101"
    r2 = chat_reply("Which trucks are delayed?")
    assert "TRK-" in r2["reply"] or "no trucks" in r2["reply"].lower()
    r3 = chat_reply("How do I record proof of delivery?")
    assert "proof of delivery" in r3["reply"].lower()
    r4 = chat_reply("blabla unknown")
    assert "suggestions" in r4
    print("chatbot OK", r["reply"][:80])

def test_dock_scheduling():
    init_db()
    assert len(list_dock_slots()) == 20 and len(list_dock_slots(status="available")) == 20
    before = next(s for s in __import__("app").all_shipments() if s["id"] == "TRK-103")
    assert before["dwell_remaining_min"] == 45
    r = book_dock_slot("DOCK-COLUMBUS-1", "TRK-103")
    assert r["ok"] is True and r["dwell_remaining_min"] == 15
    r2 = book_dock_slot("DOCK-COLUMBUS-1", "TRK-101")
    assert r2["ok"] is False  # already booked
    assert dwell_stats()["booked_slots"] == 1
    print("dock scheduling OK", r)

if __name__ == "__main__":
    test_window_and_confidence(); test_traffic_slows_eta(); test_stale_gps_lowers_confidence(); test_delay_flag()
    test_route_optimisation(); test_pod_and_detail(); test_notifications_and_fleet(); test_chatbot(); test_map_briefing_notify(); test_dock_scheduling()
    print("All 10 tests passed.")
