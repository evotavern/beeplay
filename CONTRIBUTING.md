# Contributing

## UI review and Feishu source of truth

Large UI changes are deployed from their feature branch for a phone-first review before merging.
The reviewer tests the deployed branch independently and records every observation in one persistent
Feishu document for that review round. Chat is only for announcing that a build is ready.

Each item moves through `Open` → `Implemented — awaiting review` → `Accepted`. Use `Rework requested`
or `Deferred` when appropriate. Actionable defects link to their engineering issue; the issue links back
to the Feishu review item and the deployed commit. Merge only after every blocking item is Accepted or
explicitly Deferred and the reviewer gives the green light.

## 提交代码

1. 从最新的 `main` 创建功能分支。
2. 保持一次提交只解决一个明确问题。
3. 提交前确认页面可以正常打开，脚本语法检查通过。
4. 创建 Pull Request，并说明改动内容和验证方式。

## 分支命名

- `feature/<功能名>`
- `fix/<问题名>`
- `chore/<维护内容>`

## 提交信息示例

```text
feat: add vertical game feed
fix: round notification cards
chore: update brand icons
```
