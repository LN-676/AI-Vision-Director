# Codex Skills

這份文件定義 AI 在 AutoCamTracker 專案中需要具備或優先使用的能力。

## 專案管理能力

- 能閱讀 `README.md` 與 `management/` 文件。
- 能理解 GitHub Issues、Pull Requests、branch、commit 與 review 流程。
- 能根據任務判斷應該修改前端、後端、shared、app 或 management。
- 能避免把不相關檔案一起提交。

## 前端能力

適用範圍：

- `code/frontend/`
- `code/tests/frontend/`

需要能力：

- Qt 6 UI 架構。
- MainWindow、Widget、View、Panel 設計。
- mock data 顯示。
- Live View、Detected Vehicles panel、StatusBarWidget。
- 前端只依賴 `code/shared/` 定義的資料格式，不直接依賴後端內部實作。

## 後端能力

適用範圍：

- `code/backend/`
- `code/tests/backend/`

需要能力：

- Camera / video source interface。
- YOLO / ONNX Runtime detector interface。
- detection result 處理。
- target selection 與 tracking。
- framing controller 與 digital crop controller。
- logging 與 config loading。

## Shared 能力

適用範圍：

- `code/shared/`
- `code/tests/shared/`

需要能力：

- 設計前後端共用資料格式。
- 維持 interface 穩定。
- 修改 shared 時清楚說明影響範圍。
- 避免讓 shared 依賴 frontend 或 backend 的內部細節。

## Git 能力

需要能力：

- `git status`
- `git add`
- `git commit`
- `git push`
- branch 建立與切換。
- 不直接更新 `main`。
- PR 前檢查修改範圍。

