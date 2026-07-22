# AI Vision Director Changelog

本文件記錄目前正式版本。完整舊版原始碼請透過 Git tags 查看。

This document records current releases. Complete historical source is available through Git tags.

## Unreleased

### 中文

- 新增 **AI Vision Director V2.0 beta1** PySide6 方案 A「雙監看平衡型」平行介面與 `ai-vision-director-qt` 預覽入口。
- 新增可移動、浮動、關閉及從 Window menu 重開的模組化 Dock，以及 Tracking／Identity／Performance Workspace 保存、恢復與重設。
- 修正 Python 類別名稱為 `AIVisionDirectorApp`，並保留 `AIVisonDirectorApp` 與 `AutoCamTrackerApp` 相容 alias；既有 Tkinter UI、1.0 WebSocket contract、Bonjour type 與安全策略均不變。
- 新增 `ACTF2` camera frame envelope，以 iPhone 來源 frame ID 關聯擷取、傳送、接收、解碼與推論階段；Desktop 仍相容 `ACTF1`。
- 即時效能頁新增 session／rolling throughput、P50／P95／P99、分階段掉幀率、無畫面停頓與失追區間／frame 範圍。
- 診斷頁改為模組健康總覽與結構化事件列表，提供 Healthy／Degraded／Fault／Idle、原因代碼及建議。
- JSONL telemetry schema 加入 session、severity、component 與 reason code，並保留最近事件供 UI 增量讀取。

### English

- Added the parallel **AI Vision Director V2.0 beta1** PySide6 Scheme A balanced dual-monitor UI and the `ai-vision-director-qt` preview entry point.
- Added movable, floatable, closable modular docks plus Tracking, Identity, and Performance workspace persistence and reset.
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
