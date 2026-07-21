# AI Vision Director Camera for iOS V1.0

[中文](#中文) · [English](#english)

這個 Xcode project 是 [AI Vision Director](../../README.md) 的 iPhone 相機與 DockKit 控制端，不是另一套獨立產品。Desktop 與 iOS 共用 V1.0 WebSocket contract，建議使用相同 release。

> `DockKitTester` 是目前保留的內部 target／資料夾名稱；安裝後的 App 顯示名稱是 **AI Vision Director**。

## 中文

### iOS 端負責什麼

- 使用 `AVCaptureSession` 擷取 iPhone 相機畫面與控制實體 zoom。
- 以最高約 30 FPS 的 JPEG latest-frame 串流到 Mac。
- 透過 Bonjour `_autocamtracker._tcp` 尋找 Desktop 的 `.local` WebSocket。
- 自動驗證候選端點、修正失效的舊數字 IP、重新連線。
- 解碼 V1.0 tracking JSON，檢查 sequence、target lock、誤差、信心度與 zoom。
- 關閉 DockKit System Tracking，使用 Desktop AI 的結果控制 yaw／pitch／roll。
- 提供 dead zone、smoothing、速度限制、Home、校正與 emergency STOP。

完整硬體資料流、iOS 架構圖及 Desktop 架構圖請看 [根 README](../../README.md#整體硬體與資料連接)。

### 硬體與系統需求

- iPhone 12 或更新機型。
- iOS 18 或更新版本。
- DockKit 相容穩定器，例如 Insta360 Flow 2 Pro。
- macOS 與 Xcode 16 或更新版本。
- iPhone 與 Mac 位於可互相存取的同一區域網路。

### NFC、Bluetooth 與 DockKit

NFC 用於 Flow 2 Pro 首次快速配對／喚醒，不是持續控制資料通道。首次配對後，開啟穩定器並確認 iPhone Bluetooth 已開啟，DockKit accessory 會自動重連。App 再透過 Apple DockKit API 執行馬達控制。

參考：[Insta360 NFC 配對說明](https://onlinemanual.insta360.com/flow2pro/en-us/camera/firstuse/nfconetouchpairing)／[Apple DockKit](https://developer.apple.com/documentation/dockkit)。

### 建置與安裝

1. 在 Mac 開啟 `ios/DockKitTester/DockKitTester.xcodeproj`。
2. 選擇 Target `DockKitTester` → Signing & Capabilities。
3. 啟用 Automatically manage signing，並選擇自己的 Team。
4. Bundle identifier 目前是 `com.linen.AIVisionDirector`；若簽名衝突，改成自己的唯一識別碼。
5. 以 USB 連接 iPhone、信任電腦並開啟 Developer Mode。
6. Xcode destination 選擇實體 iPhone，按 `⌘R` 安裝。
7. 首次啟動時允許 Camera 與 Local Network 權限。

### 連接 Desktop

1. 在 Mac 啟動 AI Vision Director Desktop V1.0。
2. Source 選擇 `iphone`；Desktop 會啟動 `8765` port 的 WebSocket Server 並廣播 Bonjour。
3. 開啟 iOS App。App 會先等待 Bonjour，再依序驗證 `.local` 與保存的 URL。
4. 握手成功後，驗證過的 URL 會寫回設定；如果 Mac IP 改變，不需要手動輸入新 IP。
5. Desktop 顯示 `iPhone connected` 後才會開始收到 JPEG frame。

必要時可手動輸入：

```text
ws://MacBook.local:8765/ws/tracking
```

### 安全行為

- 每個 WebSocket 候選端點有 4 秒握手期限。
- 握手完成前禁止傳送 camera frame、motor status 與 control message。
- 連線中斷、tracking data 超過 500 ms、target lost、sequence 重複／倒序或 JSON 無效時執行 STOP。
- App 切到背景或使用者斷線時清空等待中的 frame 並要求 safety stop。
- DockKit System Tracking 與 Desktop 自訂 AI Tracking 不會同時控制馬達。

### 測試

```bash
cd ios/DockKitTester
swift test
```

完整 iOS target：

```bash
xcodebuild \
  -project DockKitTester.xcodeproj \
  -scheme DockKitTester \
  -configuration Debug \
  -destination 'generic/platform=iOS' \
  CODE_SIGNING_ALLOWED=NO build
```

---

## English

This Xcode project is the iPhone camera and DockKit control component of [AI Vision Director](../../README.md), not a separate product. Desktop and iOS share the V1.0 WebSocket contract and should normally be released together.

### Responsibilities

- Capture iPhone camera frames with `AVCaptureSession` and control physical zoom.
- Stream latest-frame JPEG data to the Mac at up to approximately 30 FPS.
- Discover the desktop `.local` WebSocket through Bonjour `_autocamtracker._tcp`.
- Verify endpoints, repair a stale saved numeric IP, and reconnect automatically.
- Decode V1.0 tracking JSON and validate sequence, lock state, error, confidence, and zoom.
- Disable DockKit System Tracking and use desktop AI results for yaw, pitch, and roll.
- Apply dead zone, smoothing, rate limits, Home, calibration, and emergency STOP.

See the [root README](../../README.md#end-to-end-hardware-and-data-flow) for the complete hardware, iOS, and desktop architecture diagrams.

### Requirements

- iPhone 12 or newer.
- iOS 18 or newer.
- A DockKit-compatible gimbal such as Insta360 Flow 2 Pro.
- macOS with Xcode 16 or newer.
- Mutually reachable local-network connectivity between the iPhone and Mac.

### NFC, Bluetooth, and DockKit

NFC starts the initial Flow 2 Pro one-tap pairing flow; it is not the continuous control-data transport. After pairing, power on the gimbal with iPhone Bluetooth enabled, allow the accessory to reconnect, and let the app control it through Apple DockKit.

References: [Insta360 NFC pairing](https://onlinemanual.insta360.com/flow2pro/en-us/camera/firstuse/nfconetouchpairing) and [Apple DockKit](https://developer.apple.com/documentation/dockkit).

### Build and install

1. Open `ios/DockKitTester/DockKitTester.xcodeproj` on the Mac.
2. Select the `DockKitTester` target and open Signing & Capabilities.
3. Enable automatic signing and select your Team.
4. The current bundle identifier is `com.linen.AIVisionDirector`; use your own unique identifier if needed.
5. Connect and trust the physical iPhone, then enable Developer Mode.
6. Select the iPhone as the Xcode destination and press `⌘R`.
7. Grant Camera and Local Network permissions on first launch.

### Connect to the desktop

1. Start AI Vision Director Desktop V1.0.
2. Select the `iphone` source. The desktop starts the WebSocket server on port `8765` and advertises it through Bonjour.
3. Launch the iOS app. It prioritizes Bonjour `.local` candidates, then tries the saved URL.
4. After a verified handshake, the working endpoint replaces any stale saved IP.
5. Camera streaming starts only after the desktop reports a connected iPhone.

Manual endpoint format:

```text
ws://MacBook.local:8765/ws/tracking
```

### Safety behavior

- Each endpoint has a four-second handshake deadline.
- Camera frames, motor status, and controls are blocked before the handshake completes.
- Disconnect, 500 ms tracking timeout, target loss, invalid order, or malformed JSON triggers STOP.
- Disconnecting or backgrounding clears pending frames and requests a safety stop.
- DockKit System Tracking and custom desktop AI motor control are not allowed to compete.

### Tests

```bash
cd ios/DockKitTester
swift test
```

For a complete unsigned device-target build:

```bash
xcodebuild \
  -project DockKitTester.xcodeproj \
  -scheme DockKitTester \
  -configuration Debug \
  -destination 'generic/platform=iOS' \
  CODE_SIGNING_ALLOWED=NO build
```
