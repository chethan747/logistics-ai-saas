"""Tests for the SaaS ETA model. Run: python3 test_saas.py"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from app import predict_eta, optimise_route, record_pod, get_pod, fleet_analytics, list_notifications, init_db, shipment_detail, chat_reply, map_data, dispatcher_briefing, send_notification, list_dock_slots, book_dock_slot, dwell_stats, forecast_demand, demand_history, driver_safety_scores, safety_events, trip_cost, fleet_costs, trip_miles, temp_readings, cold_chain_status, record_temp_reading

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

def test_demand_forecasting():
    init_db()
    h = demand_history()
    assert len(h) == 64  # 8 lanes x 8 weeks of seeded history
    f = forecast_demand()
    assert f["forecast_week_start"] == "2026-11-09"
    assert len(f["lanes"]) == 8
    assert f["total_trucks_next_week"] == 80  # 16+10+13+8+7+11+6+9
    chi = next(x for x in f["lanes"] if x["lane"] == "Columbus, OH → Chicago, IL")
    assert chi["history"] == [12, 13, 12, 14, 13, 15, 14, 16]
    assert chi["avg_last_4_weeks"] == 14.5 and chi["forecast_trucks_next_week"] == 16
    assert chi["direction"] == "up" and 0.5 <= chi["confidence"] <= 0.95
    assert "Plan 16 truck(s)" in chi["recommendation"]
    one = forecast_demand("Columbus, OH → Cleveland, OH")
    assert len(one["lanes"]) == 1 and one["lanes"][0]["forecast_trucks_next_week"] == 10
    r = chat_reply("What is the demand forecast for next week?")
    assert "80" in r["reply"] or "trucks" in r["reply"].lower()
    print("demand forecasting OK", f["total_trucks_next_week"], "trucks;", chi)

def test_driver_safety_scores():
    init_db()
    assert len(safety_events()) == 8  # one seeded row per demo driver
    s = driver_safety_scores()
    assert len(s["drivers"]) == 8 and s["period_days"] == 30
    assert 80 < s["fleet_average_score"] < 85
    best = s["drivers"][0]
    assert best["driver"] == "A. Kumar" and best["safety_score"] == 96.5 and best["band"] == "Excellent"
    worst = s["drivers"][-1]
    assert worst["driver"] == "L. Brown" and worst["safety_score"] == 56.1 and worst["band"] == "At risk"
    assert worst["top_risk_factor"] == "harsh_braking" and "braking" in worst["recommendation"].lower()
    fair = next(d for d in s["drivers"] if d["driver"] == "T. Nguyen")
    assert fair["band"] == "Fair" and fair["safety_score"] == 71.7
    one = driver_safety_scores("S. Patel")
    assert len(one["drivers"]) == 1 and one["drivers"][0]["band"] == "Good"
    assert driver_safety_scores("Nobody Here")["drivers"] == []
    r = chat_reply("What is the driver safety score?")
    assert "A. Kumar" in r["reply"] and "L. Brown" in r["reply"]
    print("driver safety OK", s["fleet_average_score"], "avg;", best["driver"], best["safety_score"], ";", worst["driver"], worst["safety_score"])

def test_trip_costs():
    init_db()
    m = trip_miles({"origin": "Columbus, OH", "destination": "Chicago, IL", "remaining_miles": 180})
    assert m == 276.2  # haversine straight-line estimate, not road miles
    c = fleet_costs()
    assert len(c["shipments"]) == 8
    t101 = next(x for x in c["shipments"] if x["shipment_id"] == "TRK-101")
    assert t101["mpg"] == 6.8 and t101["fuel_gallons"] == 40.62
    assert t101["fuel_cost_usd"] == 156.39 and t101["toll_cost_usd"] == 28.5
    assert t101["driver_cost_usd"] == 108.08 and t101["total_cost_usd"] == 292.97
    assert t101["cost_per_mile_usd"] == 1.06
    # components add up to the total for every shipment
    for x in c["shipments"]:
        assert abs(x["fuel_cost_usd"] + x["toll_cost_usd"] + x["driver_cost_usd"] - x["total_cost_usd"]) < 0.02
        assert x["total_cost_usd"] > 0 and x["cost_per_mile_usd"] > 0
    # fleet totals are the sum of per-shipment costs
    assert c["fleet_totals_usd"] == {"fuel_cost_usd": 831.8, "toll_cost_usd": 121.9,
                                     "driver_cost_usd": 763.0, "total_cost_usd": 1716.7}
    assert c["fleet_trip_miles_estimate"] == 1436.8 and c["fleet_cost_per_mile_usd"] == 1.19
    assert c["most_expensive_shipment"] == "TRK-106"
    # delivered shipment uses actual minutes for driver time, not ETA
    t106 = next(x for x in c["shipments"] if x["shipment_id"] == "TRK-106")
    assert t106["driver_hours"] == 5.92 and t106["total_cost_usd"] == 341.95
    one = fleet_costs("TRK-102")
    assert len(one["shipments"]) == 1 and one["shipments"][0]["total_cost_usd"] == 119.94
    assert fleet_costs("TRK-999")["shipments"] == []
    r = chat_reply("What is the fuel and toll cost per trip?")
    assert "1716.7" in r["reply"] or "fleet total" in r["reply"].lower()
    print("trip costs OK", c["fleet_totals_usd"], "; TRK-101 $", t101["total_cost_usd"])

def test_cold_chain_alerts():
    init_db()
    assert len(temp_readings()) == 48  # 4 reefer shipments x 12 seeded readings
    cc = cold_chain_status()
    assert cc["reefer_shipments"] == 4 and len(cc["shipments"]) == 4
    assert cc["ok"] == 2 and cc["warning"] == 1 and cc["critical"] == 1
    t103 = next(s for s in cc["shipments"] if s["shipment_id"] == "TRK-103")
    assert t103["status"] == "critical" and t103["longest_excursion_readings"] == 6
    assert t103["max_deviation_c"] == 2.1 and t103["current_temp_c"] == -16.4
    assert t103["out_of_range_count"] == 6 and t103["in_range_pct"] == 50.0
    assert t103["cargo"] == "Frozen food" and t103["temp_min_c"] == -20.0 and t103["temp_max_c"] == -16.0
    t105 = next(s for s in cc["shipments"] if s["shipment_id"] == "TRK-105")
    assert t105["status"] == "warning" and t105["out_of_range_count"] == 2
    assert t105["longest_excursion_readings"] == 2 and t105["max_deviation_c"] == 0.3
    t101 = next(s for s in cc["shipments"] if s["shipment_id"] == "TRK-101")
    assert t101["status"] == "ok" and t101["out_of_range_count"] == 0
    assert t101["in_range_pct"] == 100.0 and t101["current_temp_c"] == 3.0
    # single-shipment view + non-reefer shipment has no cold-chain data
    one = cold_chain_status("TRK-101")
    assert len(one["shipments"]) == 1 and one["shipments"][0]["cargo"] == "Chilled produce"
    assert cold_chain_status("TRK-102")["shipments"] == []
    # logging a reading updates the status (demo POST path)
    r = record_temp_reading("TRK-101", 4.6)
    assert r["ok"] is True and r["shipment"]["status"] == "warning"
    assert r["shipment"]["out_of_range_count"] == 1 and r["shipment"]["current_temp_c"] == 4.6
    assert record_temp_reading("TRK-102", 3.0)["ok"] is False  # not a reefer shipment
    # chatbot answers cold-chain questions from the seeded log
    init_db()  # reset so the chatbot sees the seeded state again
    c = chat_reply("Any cold chain temperature alerts?")
    assert "TRK-103" in c["reply"] and "critical" in c["reply"].lower()
    print("cold-chain alerts OK", cc["ok"], "ok /", cc["warning"], "warning /", cc["critical"], "critical;", "TRK-103 max dev", t103["max_deviation_c"], "°C")

if __name__ == "__main__":
    test_window_and_confidence(); test_traffic_slows_eta(); test_stale_gps_lowers_confidence(); test_delay_flag()
    test_route_optimisation(); test_pod_and_detail(); test_notifications_and_fleet(); test_chatbot(); test_map_briefing_notify(); test_dock_scheduling(); test_demand_forecasting(); test_driver_safety_scores(); test_trip_costs(); test_cold_chain_alerts()
    print("All 14 tests passed.")
