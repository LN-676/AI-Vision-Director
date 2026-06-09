# Codex Rules

這份文件是 Codex 或其他 AI 在 AutoCamTracker 中必須遵守的規則。

## 最高原則

- 先讀規則，再改檔案。
- 優先保持專案結構清楚。
- 不要修改與任務無關的檔案。
- 不要直接覆蓋使用者或其他成員已經做的變更。
- 不要直接 push 到 `main`，除非使用者明確要求。

## 資料夾規則

- 前端任務主要修改 `code/frontend/`。
- 後端任務主要修改 `code/backend/`。
- 測試任務主要修改 `code/tests/`。
- 專案管理任務主要修改 `management/`。
- GitHub 協作設定主要修改 `.github/`。
- 只有在必要時才修改 `code/shared/`，且必須說明原因與影響。
- 只有在整合任務時才修改 `code/app/`。

## Shared 規則

`code/shared/` 是前端與後端的合約區。

修改 shared 前請確認：

- 這個變更是否會影響前端。
- 這個變更是否會影響後端。
- 是否需要同步修改 tests。
- 是否需要在 PR 或回報中提醒團隊。

## Git 規則

- 開始工作前先檢查 `git status`。
- commit 前再次檢查 `git status`。
- 只 stage 和任務相關的檔案。
- commit message 要清楚。
- 不要把 `.DS_Store`、build output、暫存檔或大型模型檔放進 Git。
- 若要 push，必須確認使用者已明確要求。

## 回答規則

AI 回答使用者時：

- 使用中文。
- 說明做了什麼，不要過度展開。
- 如果沒有 commit 或 push，要明確說明。
- 如果需要使用者到 GitHub 網站設定權限，也要清楚列出步驟。

