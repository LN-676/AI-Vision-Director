# AI Vision Director Changelog

本文件記錄目前正式版本。完整舊版原始碼請透過 Git tags 查看。

This document records current releases. Complete historical source is available through Git tags.

## V2.1 — 2026-07-22

### 中文

- 將 Playback 完整整合到 Source 的 Video file 頁，移除獨立 Playback Dock，並新增可保持按下狀態的影片 Loop。
- 已選定並綁定 GID 的紅框只顯示 GID 與編號，不再同時顯示 LID。
- Tracking 頁新增 Detection model 與 ReID model 下拉選單及模型重新掃描功能。
- 將 Find GID 信心門檻、Add Manual Feature 與 Start/Stop Auto Feature 整合到 Vehicle Database，移除獨立 ReID/Features Dock。
- 修正 Qt Auto Feature 只在啟動時取樣一次的問題；啟動後會持續依 frame、品質、身份與重複 gate 寫入 SQLite feature gallery。
- Desktop 與 iOS 顯示版本更新為 V2.1；iOS build 更新為 2101，既有 1.0 WebSocket contract 與 safety policy 不變。

### English

- Moved all playback controls into Source > Video file, removed the standalone Playback dock, and added a persistent pressed-state video loop toggle.
- Red selected boxes linked to a GID now display only the GID and number, without the LID.
- Added Detection model and ReID model selectors plus model refresh to the Tracking panel.
- Moved the Find GID threshold, Add Manual Feature, and Start/Stop Auto Feature controls into Vehicle Database and removed the standalone ReID/Features dock.
- Fixed Qt Auto Feature so it continues sampling frames after activation and writes accepted, quality/identity/duplicate-gated features to the SQLite gallery.
- Updated Desktop and iOS display versions to V2.1 and iOS build 2101 while preserving the 1.0 WebSocket contract and safety policy.

## V2.0 — 2026-07-22

### 中文

- Qt 影片播放改以來源媒體時鐘同步；當推論速度低於 source FPS 時跳過落後影格，不再把影片變成慢動作，iPhone 來源維持 latest-frame 無排隊策略。
- Before／After 黑邊新增精簡即時資訊：live/source FPS、frame/drop、E2E、inference、pipeline、receive、decode 與同步延遲。
- 新增雙監看最大化（雙擊監看畫面或 `Ctrl+Shift+M`）及 frame-accurate timeline 時間碼。
- 發布 **AI Vision Director V2.0** PySide6 方案 A「雙監看平衡型」平行介面與 `ai-vision-director-qt` 正式入口。
- 新增可移動、浮動、關閉及從 Window menu 重開的模組化 Dock，以及 Tracking／Identity／Performance Workspace 保存、恢復與重設。
- Vehicle Database 改為唯讀，支援首張 feature 照片懸浮預覽；雙擊車輛可進入會自動換列的圖庫，並以 Command／Ctrl／Shift 多選刪除受污染 feature。
- LID／GID 監看標籤放大至 80 px；Source 面板按來源分頁，只顯示目前來源所需的輸入欄位。
- Desktop iPhone 頁顯示／複製 WebSocket URL，iPhone App 可直接貼上；iPhone 來源會在 Qt 啟動時自動啟動 WebSocket listener。
- iOS App 升級為 V2.0 build 2001；產品版本升級不改變既有 1.0 WebSocket contract、Bonjour type 或 DockKit safety policy。
- 修正 Python 類別名稱為 `AIVisionDirectorApp`，並保留 `AIVisonDirectorApp` 與 `AutoCamTrackerApp` 相容 alias；既有 Tkinter UI、1.0 WebSocket contract、Bonjour type 與安全策略均不變。
- 新增 `ACTF2` camera frame envelope，以 iPhone 來源 frame ID 關聯擷取、傳送、接收、解碼與推論階段；Desktop 仍相容 `ACTF1`。
- 即時效能頁新增 session／rolling throughput、P50／P95／P99、分階段掉幀率、無畫面停頓與失追區間／frame 範圍。
- 診斷頁改為模組健康總覽與結構化事件列表，提供 Healthy／Degraded／Fault／Idle、原因代碼及建議。
- JSONL telemetry schema 加入 session、severity、component 與 reason code，並保留最近事件供 UI 增量讀取。

### English

- Synchronized Qt video playback to the source media clock, skipping overdue frames when inference is slower than source FPS instead of producing slow motion; iPhone input retains latest-frame, no-queue delivery.
- Added concise Before/After telemetry for live/source FPS, frame/drop counts, and end-to-end, inference, pipeline, receive, decode, and sync latency.
- Added dual-monitor maximize via double-click or `Ctrl+Shift+M` and frame-accurate timeline timecode.
- Released the **AI Vision Director V2.0** PySide6 Scheme A balanced dual-monitor UI and the `ai-vision-director-qt` production entry point.
- Added movable, floatable, closable modular docks plus Tracking, Identity, and Performance workspace persistence and reset.
- Made Vehicle Database read-only with first-feature hover previews; double-clicking a vehicle opens a responsive gallery with Command/Ctrl/Shift multi-selection for deleting contaminated features.
- Enlarged LID/GID monitor labels to 80 px and split Source controls into source-specific pages.
- Displayed and copied the desktop WebSocket URL from the iPhone source page, added paste support on iOS, and automatically started the listener for Qt iPhone sessions.
- Updated the iOS app to V2.0 build 2001 without changing the 1.0 WebSocket contract, Bonjour type, or DockKit safety policy.
- Corrected the Python class name to `AIVisionDirectorApp` while preserving `AIVisonDirectorApp` and `AutoCamTrackerApp` aliases; the Tkinter UI, 1.0 WebSocket contract, Bonjour type, and safety policy remain unchanged.
- Added the backward-compatible `ACTF2` camera envelope with an iPhone source frame ID across capture, send, receive, decode, and inference stages.
- Added session/rolling throughput, latency percentiles, stage-specific frame loss, frame stalls, and loss episodes to live performance evaluation.
- Reworked diagnostics into module health and structured event views with state, reason codes, and recommendations.
- Versioned JSONL telemetry with session, severity, component, and reason-code context plus a bounded recent-event cache.

## V1.0 — 2026-07-21

### 中文

- 統一產品名稱為 **AI Vision Director V1.0**。
- 將 Desktop 與 AI Vision Director Camera for iOS 定義為同一 monorepo 的兩個協同元件。
- 完成 Desktop／iOS V1.0 WebSocket contract 同步。
- Desktop 優先提供 `.local` URL 並以 Bonjour 廣播 `_autocamtracker._tcp`。
- iOS 自動探索 Desktop、修正保存的舊 IP、設定 4 秒握手期限並自動重連。
- WebSocket 握手完成前禁止上傳 camera frame、motor status 與 control message。
- 保留 500 ms tracking timeout、斷線 STOP、sequence 驗證與 DockKit 安全限制。
- 更新中英文文件，加入整體硬體、iOS 與 Desktop 三張架構圖。
- 保留 V1.77 在 `v1.77` tag，不再作為最新 `main`。

### English

- Unified the product identity as **AI Vision Director V1.0**.
- Defined Desktop and AI Vision Director Camera for iOS as two coordinated components in one monorepo.
- Synchronized the Desktop/iOS V1.0 WebSocket contract.
- Made the desktop prefer a stable `.local` URL and advertise `_autocamtracker._tcp` through Bonjour.
- Added iOS desktop discovery, stale-IP repair, a four-second handshake deadline, and automatic reconnect.
- Blocked camera frames, motor status, and controls until the WebSocket handshake completes.
- Preserved the 500 ms tracking timeout, disconnect STOP, sequence validation, and DockKit safety limits.
- Added bilingual documentation and the hardware, iOS, and Desktop architecture diagrams.
- Preserved V1.77 under the `v1.77` tag instead of presenting it as the latest `main`.

## Historical versions / 歷史版本

- `v1.77`: previous complete source snapshot / 前一版完整原始碼快照
- Earlier tags remain immutable references / 更早 tags 繼續作為不可變的歷史參考
