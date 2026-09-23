# beeplay / 蜂玩

Beeplay 是一个手机端优先的互动游戏与创作产品原型。首页采用短视频式游戏流，可以上下滑动切换不同的可玩内容。

## 当前内容

- 手机端优先的 App / 小程序视觉框架
- 首页竖向游戏流和滚动吸附切换
- 探索、创建、消息、个人四个功能页面
- Beeplay 品牌 Logo 与吉祥物资源
- 消息卡片、创建弹窗，以及真实持久化的试玩、点赞、收藏和分享
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
app/data.py                # 初始种子数据：8 个测试身份与各自的作品
app/avatars.py             # 单个头像 SVG，按身份换色
app/templates/base.html    # 页面外壳：顶栏、导航、弹窗
app/templates/views/       # 视图，由 htmx 换入 #viewport（/claim 除外，它整页加载）
app/templates/partials/    # 可单独换入的片段（作品网格等）
app/templates/macros.html  # 作品卡片宏
assets/js/app.js           # 交互脚本（全部使用事件委托）
assets/vendor/htmx.min.js  # htmx 2.0.4（本地打包，不用 CDN）
assets/brand/              # 品牌参考资源
assets/icons/              # Logo、吉祥物和功能图标
tools/export-icons.cjs     # 图标导出脚本
```

## 游戏流

首页只展示数据库 `works` 表中 `collection = 'feed'`、`status = 'live'` 且带有
`artifact_hash` 的记录。静态游戏文件位于
`BEEPLAY_GAMES_DIR/<artifact_hash>/index.html`：本地默认是 `./games`，部署时是
`/var/lib/beeplay/games`。数据库状态是是否展示的唯一事实来源；浏览器的游戏健康
上报负责发现无法加载或持续崩溃的文件并触发下架。

### 游戏窗口契约

首页把每个游戏放在固定比例的上方窗口中；窗口内的触摸、拖动和滑动全部属于游戏。
切换游戏只能从下方信息栏开始：上滑进入下一款，下滑回到上一款。信息栏、互动操作和
底部导航组成一个连续的 Beeplay 控制区，不覆盖游戏自己的控件。

游戏就是一个全屏手机网页，和单独打开时完全一样：宿主给游戏框的尺寸就是这台手机的屏幕
尺寸（桌面浏览器上按 390 × 844 的手机屏幕），然后等比缩小放进上方窗口，只留边，不裁切、
不变形、不重新排版。点窗口右下角的全屏按钮，同一个游戏框恢复原大小铺满屏幕，游戏状态
不丢失；顶部按钮、Esc 或手机返回手势回到游戏流。因此游戏只需要在手机上单独打开时能正常
玩，不需要任何按作品的适配设置。

游戏内注入的 Beeplay runtime 会接收 `activate` / `deactivate` 生命周期消息：离开时暂停
正在播放的音视频和 Web Audio，回来时只恢复它暂停过的内容，并派发 `beeplay:lifecycle`
事件供游戏自行处理。

## 社交数据

- 点赞与收藏要求先领取测试身份；两者都可撤销，并按「身份 + 游戏」唯一保存。
- 试玩和分享允许匿名参与。每次新挂载游戏记一次试玩；暂停后继续不会重复计数。
- 分享只在系统分享成功或分享链接确实复制成功后计数。
- 个人页的喜欢、收藏和历史标签直接读取数据库；作品卡片上的试玩/点赞数也由真实记录聚合。
- 旧的展示字符串和伪造收藏数由迁移 `0004` 删除，新的社交表从零开始，不影响用户、游戏、健康事件和运营审计。
- 游戏完成状态暂不猜测。收集十个真实游戏后，再根据它们的实际结束方式定义独立协议并回接。

## 测试身份

黑客松测试者在 `/claim` 领取 8 个预置身份之一。没有账号系统，也没有密码：
在 HTTPS 连接上提交一张身份卡片，会拿到一个 cookie（`beeplay_user=<slug>.<token>`），个人页随即
显示这个身份自己的作品。

- 领取是独占的：已被领取的身份显示为灰色，无法再次领取。
- 闲置两小时后自动释放，不需要任何后台任务；过期只是一次时间比较。
- 只要还在使用就不会被收回：每次请求都会刷新 `last_seen_at`。
- 点「切换身份」会立即释放原来的身份，把它放回可领取的池子。
- 首页、探索和游戏流不需要身份，未领取也能试玩；只有个人页会跳转到 `/claim`。
- 领取是 POST 请求，并带有 CSRF token；生产环境不会在纯 HTTP 上签发身份 cookie。仅本地开发可设置 `BEEPLAY_ALLOW_INSECURE_CLAIMS=1`。

需要提前清空全部领取状态时：

```bash
sqlite3 beeplay.db "UPDATE users SET last_seen_at = NULL, claim_token = NULL;"
```

## 团队协作约定

- `main`：可发布或演示的稳定版本
- `develop`：日常集成分支（如团队需要）
- 功能开发请使用 `feature/<功能名>` 分支
- Bug 修复请使用 `fix/<问题名>` 分支
- 通过 Pull Request 合并到 `main`

后续接入后端和数据库时，密钥、数据库地址和环境变量不要写入 HTML 或提交到仓库，使用本地 `.env` 和 GitHub Secrets。
