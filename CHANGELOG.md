# AI Vision Director Changelog

本文件記錄目前正式版本。完整舊版原始碼請透過 Git tags 查看。

This document records current releases. Complete historical source is available through Git tags.

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
