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

## Queue (next, in order — one per day, do not skip or repeat)
1. Demand forecasting — weekly truck need by lane, from seeded history
2. Driver safety score — harsh braking / speeding / idle proxy, per driver
3. Fuel, toll & cost per trip — estimated cost per shipment + fleet totals
4. Cold-chain temperature alerts — reefer temperature log + threshold alerts
5. Maintenance prediction — service due by vehicle miles / age proxy
6. White-label customer tracking — branded tracking link per tenant
7. Invoicing & quotes — quote from miles + rate, invoice per delivered trip
8. Anomaly / theft alerts — route deviation + long idle detection
9. Multi-modal — ocean/air leg in the same shipment model
10. Carbon tracking — CO2 per trip from miles + vehicle type

## Daily run checklist (for the cron agent)
1. Read this file, pick the next unchecked queue item.
2. Implement it in pure Python stdlib, with a page + API + test.
3. Run `python3 test_saas.py` — must pass. Smoke-test the new page/API with curl.
4. Mark it Done above with today's date, update README.md.
5. Push every changed/new file to https://github.com/chethan747/logistics-ai-saas via the Contents API helper, verify by listing repo contents.
6. Report to Chethan in this chat: feature, what it does, test count, repo link.
