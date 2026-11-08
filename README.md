# Logistics AI — Complete SaaS Model (Demo)

One AI product for truck delivery tracking: live tracking, predictive ETA
windows, delay risk, dispatcher dashboard, customer tracking page,
analytics, and pricing pages — in pure Python stdlib, no external packages.

## Run
```
python3 app.py
# open http://localhost:8000/ and http://localhost:8000/dashboard
```

## Test
```
python3 test_saas.py
```

## API
- `GET /api/shipments` — all shipments with ETA
- `GET /api/eta?id=TRK-101` — ETA for one shipment
- `GET /api/analytics` — totals, AI status counts, demo MAE
- `GET /api/shipment?id=TRK-101` — detail: ETA + stops + optimised route + POD + notifications
- `GET /api/route?id=TRK-101` — route optimisation (nearest-first stub, demo)
- `GET /api/pod?id=TRK-106` / `POST /api/pod` — proof of delivery (signature/photo/OTP fields)
- `GET /api/notifications` — demo notification log (not real SMS/email)
- `GET /api/fleet` — per-driver and per-vehicle analytics
- `POST /api/gps-ping` — `{"id":"TRK-101","remaining_miles":150,"speed_mph":58,"gps_age_min":2}`
- `POST /api/chat` — `{"message":"Which trucks are delayed?"}` — live AI chatbot (demo, rule-based, answers from live shipment data)
- `/map` + `GET /api/map` — live map (Leaflet/OpenStreetMap, origin → destination routes, green/amber/red by AI status)
- `/briefing` + `GET /api/briefing` — AI dispatcher briefing: delayed/at-risk/GPS-stale lists, top delay reasons, recommended actions
- `POST /api/notify` — `{"id":"TRK-101","channel":"sms","message":"..."}` — Twilio-ready: sends real SMS only if TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM and NOTIFY_TO are set; otherwise logs only and reports sent=false
- Route optimisation upgraded from nearest-first stub to nearest-first + 2-opt (heuristic, not exact TSP; no time windows/capacity yet)

## Pages
- `/dashboard` — summary cards, search, filter by AI status, shipment table
- `/shipment?id=TRK-101` — detail view
- `/portal` — customer portal (routes, status, ETA windows only)
- `/fleet`, `/notifications`, `/analytics`, `/pricing`

## Demo logins (demo only, any password)
admin@demo.local, dispatcher@demo.local, driver@demo.local, customer@demo.local

## What this is / is not
- IS: a complete SaaS skeleton to the refined spec — tenants, roles,
  shipments, ETA model, tracking, alerts logic, analytics, pricing pages.
- IS NOT: production. Simulated data, no real GPS/carrier feed, no real
  payments, no hardened auth. Real accuracy must be measured on a pilot
  fleet with real completed trips before any customer promise.

## SaaS modules in this build
1. Landing + pricing (pricing to be tested after pilot)
2. Dispatcher dashboard (summary, search, status filter)
3. Customer tracking page (`/track?id=TRK-101`) and customer portal (`/portal`)
4. AI ETA model (`app.predict_eta`) — baseline vs model, window, confidence, delay reasons
5. GPS ping API with stale-signal handling (15+ min widens window, lowers confidence)
6. Analytics (counts, status, demo MAE vs baseline) + fleet analytics
7. v2, working in demo form: route optimisation (nearest-first + 2-opt),
   proof of delivery records, notifications log, shipment detail view

## Next steps to make it production
1. Replace simulated seed with a pilot fleet GPS feed.
2. Train the ETA model on 500–1,000 real completed trips; keep the baseline comparison.
3. Add real auth, multi-tenant isolation, payments, and carrier/TMS integrations.
