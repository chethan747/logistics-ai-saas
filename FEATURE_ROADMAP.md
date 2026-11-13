# Logistics AI SaaS — Daily Feature Roadmap

One new working feature every day, tested, then pushed to GitHub the same day.
Each day: build the feature in `app.py` + tests in `test_saas.py`, run
`python3 test_saas.py`, smoke-test the server, update README, push via the
GitHub Contents API (no git CLI push).

## Done
- 2026-11-01 — v1 SaaS skeleton, dashboard, ETA, tracking, analytics
- 2026-11-01 — v2 route optimisation stub, proof of delivery, notifications log, fleet analytics, customer portal
- 2026-11-01 — Live AI chatbot in dashboard (`/chat`, `POST /api/chat`, rule-based demo)
- 2026-11-01 — iOS SwiftUI + Android Kotlin mobile skeletons (`mobile/`), iOS install guide
- 2026-11-02 — v3 live map (`/map`), route optimisation nearest-first + 2-opt, AI dispatcher briefing (`/briefing`), Twilio-ready notifications (`POST /api/notify`)
- 2026-11-08 — Dock scheduling + dwell time (`/dock`, `POST /api/dock/book`): booking a slot cuts dwell to 15 min and improves ETA
- 2026-11-09 — Demand forecasting (`/forecast`, `GET /api/forecast`): weekly truck need by lane from 8 weeks of seeded history — 4-week moving average + trend, 80 trucks total for week of 2026-11-09 across 8 lanes
- 2026-11-10 — Driver safety score (`/safety`, `GET /api/safety`): per-driver 0–100 score from seeded harsh-braking / speeding / idle event rates per 100 miles — fleet average 83.2, best A. Kumar 96.5 (Excellent), worst L. Brown 56.1 (At risk, needs braking coaching)
- 2026-11-12 — Fuel, toll & cost per trip (`/cost`, `GET /api/cost`): estimated cost per shipment = fuel (trip miles / MPG × $3.85/gal diesel) + seeded flat toll per lane + driver time (AI ETA hours × $28/hr); fleet total $1,716.70 across 8 shipments, $1.19/mile, most expensive TRK-106 $341.95 (delivered, actual minutes for driver time)
- 2026-11-12 — Cold-chain temperature alerts (`/coldchain`, `GET /api/coldchain`, `POST /api/coldchain/reading`): reefer temperature log + threshold alerts from 12 seeded readings per reefer shipment (15 min apart) — 4 reefer shipments, TRK-103 critical (6 consecutive readings out of band, max 2.1°C over the −20 to −16°C frozen band), TRK-105 warning (2 readings over 4°C), TRK-101 and TRK-107 in band; chatbot answers cold-chain questions from the log
- 2026-11-13 — Maintenance prediction (`/maintenance`, `GET /api/maintenance`, `POST /api/maintenance/service`): service due every 10,000 miles or 180 days, whichever first, from seeded odometer readings — 8 vehicles, 3 ok / 4 due soon / 1 overdue, Truck-11 overdue (950 miles / 9 days past, due 2026-11-04), Truck-04/Truck-05 due in 2 days (2026-11-15), Truck-02 next major 30,000-mile service (due 2026-12-23); chatbot answers maintenance questions; logging a completed service resets the clock

## Queue (next, in order — one per day, do not skip or repeat)
3. White-label customer tracking — branded tracking link per tenant
4. Invoicing & quotes — quote from miles + rate, invoice per delivered trip
5. Anomaly / theft alerts — route deviation + long idle detection
6. Multi-modal — ocean/air leg in the same shipment model
7. Carbon tracking — CO2 per trip from miles + vehicle type

## Daily run checklist (for the cron agent)
1. Read this file, pick the next unchecked queue item.
2. Implement it in pure Python stdlib, with a page + API + test.
3. Run `python3 test_saas.py` — must pass. Smoke-test the new page/API with curl.
4. Mark it Done above with today's date, update README.md.
5. Push every changed/new file to https://github.com/chethan747/logistics-ai-saas via the Contents API helper, verify by listing repo contents.
6. Report to Chethan in this chat: feature, what it does, test count, repo link.
