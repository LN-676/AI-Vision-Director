# Codex Workflow

這份文件給 Codex 或其他 AI 協作者閱讀，用來了解 AutoCamTracker 的管理流程與開發順序。

## 基本目標

AutoCamTracker 是自動化攝影追蹤系統。專案採用前端、後端、共用介面與整合入口分層管理。

AI 接手任務時，請先判斷任務屬於哪個區域：

- 前端：`code/frontend/`
- 後端：`code/backend/`
- 共用資料與介面：`code/shared/`
- 前後端整合：`code/app/`
- 測試：`code/tests/`
- 設定：`code/config/`
- 專案管理：`management/`
- GitHub 協作設定：`.github/`

## 工作流程

1. 先閱讀 `README.md`，確認團隊分工、Git 規則與主要版本規則。
2. 閱讀本資料夾內的 `rules.md`，確認 AI 可以修改的範圍。
3. 根據任務類型閱讀相關資料夾。
4. 修改前先確認是否會影響 `code/shared/`。
5. 修改完成後，檢查 `git status`。
6. 只提交與任務相關的檔案。
7. 不直接 push 到 `main`，除非使用者明確要求。

## 建議開發順序

1. 建立 `code/shared/` 的前後端資料合約。
2. 建立 `code/backend/` 的 camera、detection、tracking、framing 模組。
3. 建立 `code/frontend/` 的 Qt UI 與 mock data 畫面。
4. 在 `code/app/` 整合前後端。
5. 補上 `code/tests/` 測試。
6. 更新 `management/` 中的任務與決策紀錄。

## 回報格式

AI 完成工作後，請用簡短中文回報：

- 修改了哪些檔案。
- 為什麼要改。
- 是否有影響前端、後端或 shared。
- 有沒有執行檢查或測試。
- 是否尚未 commit 或 push。

