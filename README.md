# AutoCamTracker

AutoCamTracker 是自動化攝影追蹤系統的團隊專案。這個 repository 用來放程式碼、專案文件、任務管理資料與開發紀錄。

## 專案資料夾結構

- `code/frontend/`：前端畫面與 Qt UI 元件，例如視窗、Live View、車輛列表、狀態列與樣式。
- `code/backend/`：後端邏輯，例如攝影機/影片來源、YOLO 偵測、追蹤、構圖控制、裁切與 logging。
- `code/shared/`：前端與後端共用的資料格式、介面與型別。這裡是雙方合約區，修改前需要先討論。
- `code/app/`：程式入口與前後端整合。
- `code/tests/`：前端、後端、共用介面的測試。
- `code/config/`：專案設定檔，例如 camera、model path、tracking threshold。
- `code/assets/`：icons、測試影片、模型檔或其他資源。
- `management/`：專案管理文件、GitHub Project 匯入資料、會議紀錄、任務與技術決策。
- `.github/`：GitHub 協作設定，例如 CODEOWNERS 與 PR template。

## AI 開始工作前要先閱讀

如果把本專案交給 Codex 或其他 AI 協作者，請先要求 AI 閱讀以下資料，再開始修改檔案：

1. `README.md`：了解專案結構、權限分工、Git 流程與主要版本規則。
2. `management/ai-codex/workflow.md`：了解 AI 接手任務時的工作流程。
3. `management/ai-codex/rules.md`：了解 AI 修改檔案時必須遵守的規則。
4. `management/ai-codex/skills.md`：了解前端、後端、shared、Git 等任務需要的能力。
5. `management/ai-codex/hooks.md`：了解任務開始、修改前、修改後、PR 與權限設定時的檢查點。
6. `management/github-project-import/current-iteration-guide.md`：了解目前 iteration 與 GitHub Project 管理方式。
7. `management/github-project-import/current-iteration-items.csv`：了解目前拆分好的任務項目。

給 AI 的基本要求：

- 先判斷任務屬於 frontend、backend、shared、app、tests、management 或 `.github/`。
- 修改前先檢查 `git status`。
- 只修改和任務有關的檔案。
- 如果需要修改 `code/shared/`，必須說明會影響前端或後端的地方。
- 未經使用者明確要求，不要 commit、不要 push。

## 權限與分工

- `@LN-676`：專案 owner，擁有主要管理與最終合併權限。
- `@hyman1018-owner`：前端組。
- `@SCP600`：前端組。
- `@s121813910-wq`：後端組。

團隊成員可以建立 branch、commit、push 自己的 branch，並開 Pull Request。
`main` 是主要穩定版本，不建議任何人直接 push。主要版本更新需要經過 `@LN-676` 同意後才能合併。

## 可修改範圍

| 帳號 | 角色 | 主要可修改範圍 | 注意事項 |
| --- | --- | --- | --- |
| `@LN-676` | Owner / 管理者 | 全專案 | 負責審核 PR、管理 `main`、確認主要版本更新 |
| `@hyman1018-owner` | 前端組 | `code/frontend/`、`code/tests/frontend/` | 如需修改 `code/shared/`，請先在 PR 說明原因 |
| `@SCP600` | 前端組 | `code/frontend/`、`code/tests/frontend/` | 如需修改 `code/shared/`，請先在 PR 說明原因 |
| `@s121813910-wq` | 後端組 | `code/backend/`、`code/tests/backend/` | 如需修改 `code/shared/`，請先在 PR 說明原因 |

共用區域規則：

- `code/shared/`：前端與後端共用的資料格式與介面，修改前要先確認影響範圍。
- `code/app/`：前後端整合入口，主要由 `@LN-676` 或整合負責人修改。
- `management/`：專案管理文件與任務資料，主要由 `@LN-676` 維護。
- `.github/`：GitHub 協作設定，主要由 `@LN-676` 維護。
- `README.md`：團隊規則文件，主要由 `@LN-676` 維護。

## 開發流程

1. 下載專案：

   ```bash
   git clone https://github.com/LN-676/AutoCamTracker.git
   cd AutoCamTracker
   ```

2. 建立自己的功能 branch：

   ```bash
   git checkout -b feature/your-task-name
   ```

3. 修改負責區域的檔案。

4. commit：

   ```bash
   git add .
   git commit -m "feat: describe your change"
   ```

5. push 自己的 branch：

   ```bash
   git push -u origin feature/your-task-name
   ```

6. 到 GitHub 開 Pull Request，等待 review。

## Git 操作步驟

### 第一次下載專案

```bash
git clone https://github.com/LN-676/AutoCamTracker.git
cd AutoCamTracker
```

### 每次開始工作前

先切回 `main`，並更新到最新版本：

```bash
git checkout main
git pull origin main
```

再建立自己的 branch：

```bash
git checkout -b feature/your-task-name
```

branch 命名建議：

- `feature/frontend-live-view`
- `feature/backend-video-source`
- `fix/backend-tracking-error`
- `docs/update-readme`

### 查看目前狀態

```bash
git status
```

這個指令可以確認自己改了哪些檔案、哪些檔案還沒加入 commit。

### 加入修改內容

```bash
git add .
```

如果只想加入單一檔案：

```bash
git add path/to/file
```

### 建立 commit

```bash
git commit -m "feat: describe your change"
```

commit 訊息建議格式：

- `feat: add live view widget`
- `fix: handle camera open failure`
- `docs: update project workflow`
- `refactor: simplify tracking interface`

### push 自己的 branch

```bash
git push -u origin feature/your-task-name
```

push 完後，到 GitHub 開 Pull Request，請求 review。

### 後續同一個 branch 繼續更新

修改檔案後：

```bash
git status
git add .
git commit -m "feat: describe next change"
git push
```

## 主要版本更新規則

`main` 是主要穩定版本，請不要直接更新 `main`。

正確流程：

1. 從最新的 `main` 建立自己的 branch。
2. 在自己的 branch 修改程式。
3. commit 修改內容。
4. push 自己的 branch。
5. 到 GitHub 開 Pull Request。
6. 等待 `@LN-676` review。
7. 通過 review 後，才合併回 `main`。

請不要做：

- 不要直接在 `main` 上寫功能。
- 不要直接 push 到 `main`。
- 不要把不相關的檔案一起 commit。
- 不要修改其他組負責的資料夾，除非 PR 有清楚說明原因。
- 不要把大型模型檔、暫存檔、build output、`.DS_Store` 放進 Git。

## Pull Request 注意事項

開 PR 時請寫清楚：

- 這次改了什麼。
- 修改的是前端、後端、shared、app integration，還是文件。
- 有沒有影響其他組。
- 如果改到 `code/shared/`，要說明前端與後端需要怎麼配合。
- 如果還沒完成，請在 PR 說明目前完成到哪裡。

PR 被要求修改時，直接在同一個 branch 繼續 commit 並 push，不需要開新的 PR。

## 開發紀錄與 Log

一般開發流程不一定要求每個人每天寫很長的開發 log，但需要留下足夠紀錄，讓其他人知道目前進度與變更原因。

建議使用以下方式留下紀錄：

- commit message：每次 commit 簡短說明做了什麼。
- Pull Request 說明：說明這次修改內容、影響範圍、是否需要其他組配合。
- GitHub Issue comment：遇到問題、改變方向、完成階段性進度時更新。
- `management/meeting-notes/`：放會議紀錄。
- `management/decisions/`：放重要技術決策，例如架構、工具、資料格式選擇。
- `management/開發日誌（英文）/` 或 `management/AutoCamTracker_Development/`：放正式開發日誌、PDF 或彙整文件。

如果要了解其他人的開發狀態，優先看：

1. GitHub Pull Request。
2. GitHub Issues。
3. commit history。
4. `management/meeting-notes/`。
5. `management/decisions/`。
6. 開發日誌資料夾。

團隊不需要把所有細節都寫成 log，但重要變更、問題、決策和完成進度要留下紀錄。

## 分支規則

- `main`：穩定版本，只能透過 Pull Request 更新。
- `feature/...`：新功能。
- `fix/...`：錯誤修正。
- `docs/...`：文件更新。

## 給其他 AI 或協作者的規則

前端工作主要修改 `code/frontend/`，不要直接改 `code/backend/`。
後端工作主要修改 `code/backend/`，不要直接改 `code/frontend/`。
前後端需要共用資料時，使用 `code/shared/`。
如果需要修改 `code/shared/`，請先說明原因，因為這會影響兩組人。
