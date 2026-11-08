# Install the Logistics AI app on your iPhone (Mac + Xcode)

You need: a Mac with Xcode, your iPhone, and both on the SAME Wi-Fi.
No paid Apple Developer account needed for your own phone.

## Step 1 — Start the server on your Mac
```bash
cd ~/workspace/logistics-ai-saas
python3 app.py
```
It now listens on 0.0.0.0, so a phone on the same Wi-Fi can reach it.
Keep this terminal running while you use the app.

Find your Mac's LAN IP:
- System Settings → Wi-Fi → your network → Details → IP address, e.g. 192.168.1.10
- Or in Terminal: `ipconfig getifaddr en0`
Write it down — you need it in Step 3.

## Step 2 — Create the Xcode project
1. Xcode → File → New → Project → iOS → App → Next
2. Product Name: LogisticsAI, Interface: SwiftUI, Language: Swift → Next → Create
3. Delete the default `ContentView.swift` that Xcode created (or replace it).
4. Drag in, or File → Add Files, these 3 files from `mobile/ios/`:
   - `LogisticsAIApp.swift`
   - `ContentView.swift`
   - `ApiClient.swift`
   - Tick "Copy items if needed" and your app target.
5. If Xcode asks about the old default App file, make sure only
   `LogisticsAIApp.swift` has `@main` — delete the other `@main` file.

## Step 3 — Point the app at your Mac (critical)
In `ApiClient.swift`, change:
```swift
static let BASE_URL = "http://127.0.0.1:8000"
```
to:
```swift
static let BASE_URL = "http://192.168.1.10:8000"  // your Mac LAN IP from Step 1
```
Do NOT use localhost / 127.0.0.1 on the phone — that means the phone
itself, not your Mac, so the app would get no data.

## Step 4 — Allow plain HTTP (critical, otherwise iOS blocks it)
The demo server is http, not https, so iOS blocks it by default.
In Xcode, open `Info.plist` (or add a new property list if your project
uses the target's Info tab):
- Add key: `NSAppTransportSecurity` (Dictionary)
  - Inside it, add: `NSAllowsArbitraryLoads` = YES (Boolean)
For a production app, replace this with https, not this blanket allow.

## Step 5 — Signing (free, personal team)
1. In the project target → Signing & Capabilities → tick
   "Automatically manage signing"
2. Team: choose your Apple ID (add it in Xcode → Settings → Accounts
   if it's not there). No paid account needed.
3. Bundle Identifier: make it unique, e.g. `com.chethan.logisticsai`
   (if Xcode says it's taken, add a number at the end).

## Step 6 — Run it on your iPhone
1. Plug your iPhone into the Mac with a cable, unlock it, tap Trust.
2. In Xcode, at the top, change the run destination from a simulator
   to your iPhone.
3. Press Run (▶). First build takes a minute.
4. If the phone says "Untrusted Developer": on the iPhone go to
   Settings → General → VPN & Device Management → tap your Apple ID
   → Trust. Then open the app again.
5. The app has 2 tabs: Shipments and AI Chat. Try the chat:
   "Which trucks are delayed?" and "What is TRK-101 ETA?"

## Troubleshooting
- App opens but list is empty: Mac server not running, phone/Mac not
  on the same Wi-Fi, wrong LAN IP in ApiClient.swift, or macOS firewall
  blocking Python — allow incoming connections for Python in
  System Settings → Network → Firewall.
- "Could not launch" / signing error: check Bundle ID is unique and
  Team is your Apple ID, not "None".
- App disappears after 7 days: that's normal for free personal signing.
  Just plug in and Run again from Xcode to reinstall it.
- For other people to install it (not just you): you need a paid
  Apple Developer account + TestFlight / App Store — that's a separate
  step, not needed for your own phone.
