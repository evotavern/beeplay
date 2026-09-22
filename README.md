# beeplay / 蜂玩

Beeplay 是一个手机端优先的互动游戏与创作产品原型。首页采用短视频式游戏流，可以上下滑动切换不同的可玩内容。

## 当前内容

- 手机端优先的 App / 小程序视觉框架
- 首页竖向游戏流和滚动吸附切换
- 探索、创建、消息、个人四个功能页面
- Beeplay 品牌 Logo 与吉祥物资源
- 消息卡片、创建弹窗、点赞、收藏、分享等交互原型
- 透明底 PNG 图标资源，可用于 Web、小程序和 App

## 本地预览

原型现在由 FastAPI + Jinja 模板提供服务：

```bash
uv sync
uv run uvicorn app.main:app --reload --port 8010
```

然后访问 http://127.0.0.1:8010/ 。

如果需要重新生成图标：

```bash
npm install
npm run icons
```

## 项目结构

```text
app/main.py                # FastAPI 应用入口
app/data.py                # 页面种子数据（后续由数据库取代）
app/templates/index.html   # 当前交互原型模板
assets/brand/              # 品牌参考资源
assets/icons/              # Logo、吉祥物和功能图标
tools/export-icons.cjs     # 图标导出脚本
```

## 团队协作约定

- `main`：可发布或演示的稳定版本
- `develop`：日常集成分支（如团队需要）
- 功能开发请使用 `feature/<功能名>` 分支
- Bug 修复请使用 `fix/<问题名>` 分支
- 通过 Pull Request 合并到 `main`

后续接入后端和数据库时，密钥、数据库地址和环境变量不要写入 HTML 或提交到仓库，使用本地 `.env` 和 GitHub Secrets。
