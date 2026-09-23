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

## 从想法生成游戏

`/create` 支持一次性生成：输入玩法 → 生成期间填写名称、分类、图标、封面颜色和介绍 → 试玩 → 主动发布。
仍使用现有的随机身份。草稿绑定本次身份领取；身份被重新领取后，新持有人无法访问旧草稿。
每个身份最多一个生成任务。任务和草稿存储在 SQLite，刷新可恢复；进程重启会将中断的请求标记失败，不会自动重复扣费。

本地启动（独立工作目录有独立数据库和游戏目录）：

```bash
cp .env.example .env
# 编辑 .env，BEEPLAY_EVOMAP_KEYS 是完整 bearer key 的 JSON 数组。
uv sync
uv run uvicorn app.main:app --env-file .env --host 127.0.0.1 --port 8021
```

默认 API 为 `https://api.evomap.ai/v1/chat/completions`，模型为 `evomap-gemini-3.1-pro-preview`。
`BEEPLAY_EVOMAP_BASE_URL`、`BEEPLAY_EVOMAP_MODEL`、`BEEPLAY_GENERATION_MAX_TOKENS`（默认 8192）、
`BEEPLAY_GENERATION_TIMEOUT_S`（默认 180）和 `BEEPLAY_GENERATION_WORKERS`（默认 2）均可配置。
**运行一个 uvicorn 进程，不使用 `--workers`。** 进程内有有界后台线程，网络调用不占用页面请求。
服务器部署时把同样的环境变量放入现有 `/etc/beeplay/beeplay.env`，不要提交真实密钥。

密钥按最近使用顺序轮换；401/403/402 或明确的 `insufficient_quota`/`quota_exceeded` 会停用该 key，
普通 429 按 `Retry-After` 冷却。仅明确的这些拒绝会尝试另一个 key，每次任务每个 key 最多一次。
网络中断或其他服务错误不自动重放，用户可以重新生成。没有配置密钥时页面明确显示不可用。
额度字段尚无公开验证的 Evomap 契约；不猜测余额接口，不把本地累计使用量当成剩余额度。

### 生成速度与试玩观测

```bash
uv run python -m app.ops generations
uv run python -m app.ops generations --id GENERATION_ID
uv run python -m app.ops generation-keys
uv run python -m app.ops generation-keys --enable KEY_IDENTIFIER
```

CLI 使用进程环境变量；本地读取 `.env` 可运行：

```bash
uv run python -c 'from dotenv import load_dotenv; load_dotenv(); from app.ops import main; main()' generation-keys
```

本地也可直接运行 `./deploy/local.sh` 启动；更改 `.env` 后重启该进程。
`generations` 按模型汇总最近 100 个任务（`--limit` 可改）的 p50/p95：排队、完整 provider 响应、验证、
可试玩、资料填写、填写完成后的空等、进入试玩耗时。每次尝试保留非秘密 key 标识、模型、HTTP 状态、
响应 token usage（若提供）、允许列表内的 rate-limit headers 和延迟。余额没有被 provider 明确返回时为 unknown。
试玩记录 opened / loaded / error / timeout / closed（关闭时记录时长）及最终发布，全部关联 generation ID。
浏览器信号用于产品观测，不能当作可信的游戏质量证明；未上报关闭的会话不推断时长。

初始优化假设：**开始试玩前的准备时间 ≈ max(生成时间, 填写时间)**。先看 `playable_ms` 与
`idle_wait_ms` 的 p50/p95、失败比例，再调整模型、提示词或输出 token 上限。不要仅追求短输出导致游戏被截断。
`provider_ms` 是完整非流式响应时间，不是首 token 时间。当前提供真实阶段和耗时，不显示虚假的完成百分比，
不执行未完成代码，也不做自动多模型竞速。生成 HTML 限制为内联脚本/样式和 data/blob 素材，无外部依赖。
试玩使用隔离 iframe 和 CSP；`/games/` 的直接访问也加上 sandbox 响应头（部署需更新 Nginx 配置）。
