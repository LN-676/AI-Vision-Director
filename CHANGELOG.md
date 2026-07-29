# AI Vision Director Changelog

本文件記錄目前正式版本。完整舊版原始碼請透過 Git tags 查看。

This document records current releases. Complete historical source is available through Git tags.

## V3.0.0b1 — 2026-07-30

### 中文

- 新增手機熱點與有線 iPad Remote Console 啟動器，自動偵測、顯示並複製
  當次可用的數字 IP 網址。
- Desktop Source → iPhone 頁面新增 Tablet Remote URL，並與 WebSocket
  位址同步更新。
- 新增 Desktop 馬達輸出安全控制，只有 iPhone 輸入、追蹤啟用且
  DockKit ready 時才發布追蹤命令。
- iOS 新增相機校正資訊、自訂 DockKit 追蹤節奏、Flow 2 Pro 連線指引與
  自動重新監聽。
- 強化 Qt 工作區儲存、還原與預設版面重設。
- iOS Marketing Version 維持 `3.0.0`，build 更新為 `3002`；套件與顯示
  版本更新為 `V3.0.0b1`。

### English

- Added wired and Personal Hotspot iPad Remote Console launchers that detect,
  display, and copy the current numeric-IP URL.
- Added a synchronized Tablet Remote URL to Desktop Source → iPhone.
- Added guarded Desktop motor output that publishes tracking commands only
  while iPhone input, tracking, and DockKit readiness are all active.
- Added camera calibration, custom DockKit tracking cadence, Flow 2 Pro
  connection guidance, and automatic listener recovery on iOS.
- Improved Qt workspace persistence, restoration, and default-layout reset.
- Kept the iOS Marketing Version at `3.0.0`, incremented the build to `3002`,
  and updated package and display versions to `V3.0.0b1`.

## V3.0.0a1 — 2026-07-29

### Phase 6 advanced cloud

- Added organization/member/device ownership and tenant-scoped Firebase claims.
- Added Pub/Sub lifecycle topics, dead lettering, a durable event envelope, and
  a PostgreSQL event outbox.
- Added cloud benchmark submission, CPU and opt-in NVIDIA L4 Cloud Run jobs, and
  a CUDA benchmark worker with model digest verification.
- Added a tenant model registry, notification channels and alert rules, Cloud
  Monitoring email routing, and a benchmark failure policy.
- Added long-term BigQuery telemetry storage with daily partitioning and tenant
  and event-type clustering.
- Added live Before/After monitors to the tablet Remote Console.
- Added per-frame FastAPI/browser timing, up-to-10-FPS tablet previews, and
  low-bandwidth 960px JPEG publication.
- Fixed Remote commands on insecure private-LAN HTTP browsers by providing a
  UUID fallback and connected every high-level command to the Qt desktop UI.
- Stabilized DockKit discovery by preserving the listener across foreground
  transitions, adding bounded retry after stream failure, and showing an
  actionable Flow 2 Pro/NFC timeout diagnosis.

### 中文

- 建立上網部署 Phase 0 邊界：`Repository`、`SystemStatusQuery`、
  `VehicleQuery`／`VehicleCommand` 與 `EventSink`。
- 平板 Remote Console 新增即時 Before／After 雙監看畫面。
- Remote 雙監看加入逐幀 FastAPI、網路與瀏覽器解碼時間，最高 10 FPS，
  並以 960px 低流量 JPEG 傳輸。
- 修正區網 HTTP 瀏覽器缺少 `crypto.randomUUID()` 導致所有 Remote
  按鈕失效，並把所有高階命令完整串接至 Qt 桌面 UI。
- iOS App 保留跨前景切換的 DockKit listener，只在 stream 錯誤時做有界
  重試，並在 Flow 2 Pro／NFC 沒有 dock event 時顯示可操作的診斷。
- 新增 OpenAPI 3.1 schema，定義 status、vehicle query/command 與 event
  delivery，所有 mutation 使用 idempotency key。
- 新增一對一、衝突即拒絕的 `(node_id, local_id) <-> cloud_id` mapping
  contract 與 reference in-memory adapter。
- 新增本機 read-only FastAPI，提供 system status、vehicles、sessions、
  events 與 runtime OpenAPI；SQLite 強制使用 `mode=ro` 與 `query_only`。
- 新增 PostgreSQL 正式 schema、Alembic migration、SQLAlchemy adapter、
  Docker Compose、可重跑的 SQLite/telemetry importer，以及具 lease、
  exponential backoff、dead-letter 與 idempotent projection 的 Edge outbox。
- 新增 Phase 3 public write boundary：Firebase revoked-token verification、
  RBAC/node scope、PATCH vehicle optimistic concurrency、append-only audit、
  PostgreSQL rate limit、CORS allowlist 與 Docker secrets。
- 新增 Phase 4 React Mission Control：typed read-only client、overview、
  vehicles、sessions、events、完整 loading/error/empty states，以及具
  offline awareness 與 bounded exponential backoff 的 WebSocket telemetry。
- 新增 Phase 5 Google Cloud 部署來源：Firebase Hosting、Cloud Run API
  與 Dashboard、Cloud SQL PostgreSQL、Cloud Storage、Artifact Registry、
  Secret Manager、Logging/Monitoring、HTTPS/WSS、Pub/Sub billing 通知，
  以及 Cloud Run US$1 原生支出上限的安全邊界。
- 同步 iOS 顯示版本為 `V3.0.0a1`，Marketing Version 更新為 `3.0.0`，
  build 更新為 `3001`。
- 將版本標籤更新為 `AI-Vision-Director V3.0.0a1`，套件版本更新為
  `3.0.0a1`；既有 WebSocket protocol version `1.0` 保持不變。

### English

- Established Phase 0 online-deployment boundaries: `Repository`,
  `SystemStatusQuery`, `VehicleQuery`/`VehicleCommand`, and `EventSink`.
- Added an OpenAPI 3.1 schema for status, vehicle query/command, and event
  delivery, with idempotency keys on every mutation.
- Added a conflict-safe, one-to-one `(node_id, local_id) <-> cloud_id` mapping
  contract and reference in-memory adapter.
- Added a local read-only FastAPI for system status, vehicles, sessions,
  events, and runtime OpenAPI, with SQLite forced into `mode=ro` and
  `query_only`.
- Added the formal PostgreSQL schema, Alembic migration, SQLAlchemy adapter,
  Docker Compose, repeatable SQLite/telemetry importer, and an Edge outbox
  with leases, exponential backoff, dead-letter handling, and idempotent
  projection.
- Added the Phase 3 public write boundary with Firebase revoked-token
  verification, RBAC/node scope, optimistic-concurrency vehicle PATCH,
  append-only audit, PostgreSQL rate limiting, a CORS allowlist, and Docker
  secrets.
- Added the Phase 4 React Mission Control with a typed read-only client,
  overview, vehicles, sessions, events, complete loading/error/empty states,
  and offline-aware WebSocket telemetry with bounded exponential backoff.
- Added Phase 5 Google Cloud deployment sources for Firebase Hosting, Cloud Run
  API/dashboard services, Cloud SQL PostgreSQL, Cloud Storage, Artifact
  Registry, Secret Manager, Logging/Monitoring, HTTPS/WSS, Pub/Sub billing
  notifications, and a safe boundary for the native US$1 Cloud Run spend cap.
- Synchronized the iOS display version to `V3.0.0a1`, Marketing Version to
  `3.0.0`, and build number to `3001`.
- Updated the release label to `AI-Vision-Director V3.0.0a1` and package
  version to `3.0.0a1` while preserving WebSocket protocol version `1.0`.

## V2.3 — 2026-07-24

### 中文

- Quick Auto 預設 Feature limit 從 50 降為 20，以縮短 Feature Gallery 建立時間。
- Quick Auto 新增獨立進度彈窗，顯示目前模型、Feature Gallery 建立進度、測試輪次、已分析 frame 與完成百分比。
- 新增已耗時間、預估剩餘時間與預計完成時間。
- 新增 Pause／Resume 與 Stop；停止時會合作式中止並安全關閉 detector。
- Benchmark 操作列新增 Show Progress，可重新叫出進度視窗。
- Run、Show Progress、Import 與 Export 四顆按鈕改為同排等寬排列。
- Desktop 顯示版本更新為 V2.3，套件版本更新為 2.3.0；1.0 WebSocket contract 與 iOS V2.2 保持不變。

### English

- Reduced the default Quick Auto Feature limit from 50 to 20 to shorten feature-gallery enrollment.
- Added a dedicated Quick Auto progress window showing the current model, feature-gallery enrollment, measured round, analyzed frames, and completion percentage.
- Added elapsed time, estimated remaining time, and estimated finish time.
- Added cooperative Pause/Resume and Stop controls with safe detector cleanup.
- Added Show Progress to reopen the progress window.
- Distributed Run, Show Progress, Import, and Export evenly across one action row.
- Updated the Desktop display version to V2.3 and the package version to 2.3.0 while preserving the 1.0 WebSocket contract and iOS V2.2.

## V2.2 — 2026-07-24

### 中文

- 新增 Benchmark Center，可從工具列或 Benchmark workspace 開啟，最多選擇五個 Detection 模型依序比較。
- 新增 100 萬分制跑分、六軸比例圖、原始 Detection／Tracking／ReID／Framing／Control／System 指標表與資料覆蓋率。
- 新增 `model-benchmark` headless runner、Golden Dataset v1 規格，以及 COCO／MOTChallenge 標準格式匯出。
- 將 Detection model 與 ReID model 從 Tracking 拆成獨立 Models 頁，支援連結外部模型與開啟模型資料夾。
- Detection 提示支援 Ultralytics `.pt` 與 exported `.onnx`；ReID 支援 `.onnx` embedding model。
- Playback 的 Record 現在會建立 live/iPhone closed-loop benchmark session，保存 source video 與待標註 observations，不會把模型輸出誤當 ground truth。
- Desktop 與 iOS 顯示版本更新為 V2.2；iOS build 更新為 2201，既有 1.0 WebSocket contract 與 safety policy 不變。

### English

- Added Benchmark Center with toolbar and workspace entry points and sequential comparison for up to five Detection models.
- Added a one-million-point score, six-axis ratio chart, raw Detection/Tracking/ReID/Framing/Control/System table, and evaluation coverage.
- Added the headless `model-benchmark` runner, Golden Dataset v1 contract, and COCO/MOTChallenge format exports.
- Moved Detection and ReID selection from Tracking into an independent Models page with external-model linking and model-folder access.
- Detection supports Ultralytics `.pt` and exported `.onnx`; ReID supports `.onnx` embedding models.
- Playback Record now creates a live/iPhone closed-loop benchmark session with source video and pending observations without treating predictions as ground truth.
- Updated Desktop and iOS display versions to V2.2 and iOS build 2201 while preserving the 1.0 WebSocket contract and safety policy.

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
