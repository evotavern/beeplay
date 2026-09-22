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
app/main.py                # FastAPI 应用入口与路由
app/models.py              # SQLAlchemy 模型
app/db.py                  # 引擎、SQLite pragma、种子数据写入
app/repository.py          # 数据查询层
app/data.py                # 初始种子数据（仅首次启动时写入数据库）
app/templates/base.html    # 页面外壳：顶栏、导航、弹窗
app/templates/views/       # 五个视图，由 htmx 换入 #viewport
app/templates/partials/    # 可单独换入的片段（作品网格等）
app/templates/macros.html  # 作品卡片宏
assets/js/app.js           # 交互脚本（全部使用事件委托）
assets/vendor/htmx.min.js  # htmx 2.0.4（本地打包，不用 CDN）
assets/brand/              # 品牌参考资源
assets/icons/              # Logo、吉祥物和功能图标
tools/export-icons.cjs     # 图标导出脚本
```

## 游戏流

首页只展示数据库 `works` 表中 `collection = 'feed'`、且游戏文件实际存在的
记录。静态游戏文件位于 `BEEPLAY_GAMES_DIR/<artifact_hash>/index.html`：本地
默认是 `./games`，部署时是 `/var/lib/beeplay/games`。因此一条信息流记录只有
在对应的游戏文件存在时才会显示并可启动。

## 团队协作约定

- `main`：可发布或演示的稳定版本
- `develop`：日常集成分支（如团队需要）
- 功能开发请使用 `feature/<功能名>` 分支
- Bug 修复请使用 `fix/<问题名>` 分支
- 通过 Pull Request 合并到 `main`

后续接入后端和数据库时，密钥、数据库地址和环境变量不要写入 HTML 或提交到仓库，使用本地 `.env` 和 GitHub Secrets。
