# NetPresence mobile

* `core/` - platform-independent TypeScript (signing contract, RSSI aggregation, session flow). Fully tested.
* `app/` - React Native 0.76 shell: enrol screen, one **Mark me present** button, BLE lab logger.
  * Android: `android/app/src/main/java/com/netpresence/NetPresenceModule.kt` (Keystore EC P-256, BLE advertise + LOW_LATENCY scan).
  * iOS: `ios/NetPresence/NetPresenceNative.{h,m}` (Secure Enclave P-256, CoreBluetooth, AllowDuplicates scan, foreground only).
  * Android peers are identified by manufacturer data (0xFFFF + ASCII id) in the scan response; iOS peers by LocalName `NP-<id>`;
    each side's scanner understands both.

## Build
```bash
cd mobile/app && npm install
npx react-native run-android          # needs Android SDK + device (BLE does not work on emulators)
cd ios && pod install && cd .. && npx react-native run-ios --device   # needs Xcode + real iPhone
```
Enter the server URL (reachable from the phones, ideally the classroom LAN or an HTTPS tunnel), roll number and name on first launch.

## Verification status
| Piece | Status |
|---|---|
| `core` unit tests (21) + live tests against real server | passing |
| App TypeScript typecheck; Metro bundle for Android + iOS | passing |
| Kotlin module, Obj-C module, Gradle/Xcode build, permissions flow | **never compiled or run** (no SDK/Xcode in the dev sandbox) |
| Real BLE RSSI behaviour, Secure Enclave signing accepted by server | **unverified on devices** |
| Obj-C file registered in `project.pbxproj` by hand | verify Xcode opens it and builds; re-add the files in Xcode if not |

First device checklist: (1) enrol on one Android and one iPhone; (2) confirm the server accepts both signatures
(iOS key is wrapped as SPKI to match); (3) run *BLE lab* between the two and confirm each hears the other; (4) run a real
session with 4+ phones and compare against sim expectations.

## Getting installable builds without a Mac or local SDK
`.github/workflows/mobile.yml` builds in GitHub Actions (free macOS/Linux runners): push the repo to your own GitHub,
open Actions -> "Mobile builds" -> latest run -> Artifacts.
* `netpresence-android-apk` - install directly (enable "install unknown apps"). Signed with the debug key; test use only.
* `netpresence-ios-unsigned-ipa` - unsigned. Install on an iPhone from Windows/Linux with Sideloadly or AltStore using a
  free Apple ID (re-sign every 7 days; AltStore can refresh over Wi-Fi). A paid Apple Developer account ($99/yr) is only
  needed for TestFlight (over-the-air install, 90-day builds).
The workflow has not been run yet; the first run may need small fixes (send the log).
Android release builds allow cleartext `http://` for LAN testing; remove `usesCleartextTraffic` before real deployment.
