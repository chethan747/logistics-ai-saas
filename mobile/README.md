# Mobile apps — iOS and Android

## 1. Mobile web app (works TODAY on iOS and Android)
Open the SaaS in a phone browser: `http://localhost:8000/dashboard` and
`http://localhost:8000/chat` — both are responsive and include the chatbot.
No install needed for a demo. For a PWA install, add the page to Home Screen
on iOS (Share → Add to Home Screen) or Android (Install app).

A dedicated mobile page is also at `/mobile` in the SaaS server.

## 2. Native iOS app (SwiftUI skeleton)
Folder: `mobile/ios/`
- `ApiClient.swift` — fetches `/api/shipments`, `/api/eta`, `/api/chat`
- `ContentView.swift` — shipment list, detail/ETA, and chatbot screen
- Open in Xcode, set `BASE_URL` to your SaaS server (use your computer's
  LAN IP, not localhost, from a real phone), then Run on a simulator/device.
- This is a skeleton, not an App Store build: no signing, no push, no
  background GPS. Add those in Xcode / App Store Connect before release.

## 3. Native Android app (Kotlin / Jetpack Compose skeleton)
Folder: `mobile/android/`
- `ApiClient.kt` — same API calls, using HttpURLConnection (stdlib-style,
  no extra Gradle deps in the skeleton)
- `MainActivity.kt` — shipment list, detail/ETA, and chatbot screen
- Open in Android Studio, set `BASE_URL` to your SaaS server LAN IP,
  then Run on an emulator/device.
- This is a skeleton, not a Play Store build: no signing, no push,
  no background GPS. Add those in Android Studio / Play Console before release.

## Shared API used by all three
- GET /api/shipments, GET /api/eta?id=TRK-101, GET /api/analytics
- POST /api/chat {"message": "Which trucks are delayed?"}
- POST /api/gps-ping, GET /api/shipment?id=TRK-101

Demo data only. Real GPS, auth, and payments must be added before production.
