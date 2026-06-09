# Codex Hooks

這份文件定義 AI 在看到特定任務時應該觸發的檢查與動作。這裡的 hooks 是管理規則，不是程式自動執行的 Git hooks。

## 任務開始 Hook

當 AI 收到任何開發或管理任務時：

1. 執行或檢查 `git status`。
2. 判斷任務區域：frontend、backend、shared、app、tests、management、github。
3. 如果任務會動到 `code/shared/`，先提醒 shared 會影響前後端。
4. 如果任務需要 push，確認使用者是否明確要求。

## 修改前 Hook

修改檔案前：

- 確認目標資料夾。
- 確認沒有要改到其他組負責的區域。
- 如果必須跨區修改，回報原因。

## 修改後 Hook

修改完成後：

1. 檢查 `git status`。
2. 確認沒有 `.DS_Store`、build output、暫存檔被加入。
3. 回報修改檔案與影響範圍。
4. 若使用者要求 commit，再進行 stage 和 commit。
5. 若使用者要求 push，再推送到 GitHub。

## PR Hook

準備 Pull Request 時：

- 確認 branch 不是 `main`。
- 確認 PR 內容有說明修改範圍。
- 如果改到 `code/shared/`，PR 內要說明前後端影響。
- 如果改到 `.github/` 或 `README.md`，需要 `@LN-676` review。

## 權限 Hook

如果使用者要求修改 GitHub 權限：

1. 先更新 repo 內可版本管理的 `.github/CODEOWNERS`。
2. 說明 CODEOWNERS 只負責 review 規則，不等於 GitHub collaborator 權限。
3. 提醒使用者仍需到 GitHub Settings 設定 collaborators 與 branch protection。

