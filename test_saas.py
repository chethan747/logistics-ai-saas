"""Tests for the SaaS ETA model. Run: python3 test_saas.py"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from app import predict_eta, optimise_route, record_pod, get_pod, fleet_analytics, list_notifications, init_db, shipment_detail

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
    assert r["optimised_order"] == ["A", "B"] and r["total_miles_estimate"] == 190
    print("route optimisation stub OK", r["optimised_order"])

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

if __name__ == "__main__":
    test_window_and_confidence(); test_traffic_slows_eta(); test_stale_gps_lowers_confidence(); test_delay_flag()
    test_route_optimisation(); test_pod_and_detail(); test_notifications_and_fleet()
    print("All 7 tests passed.")
