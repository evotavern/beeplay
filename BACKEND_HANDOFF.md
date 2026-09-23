# BeePlay 后端交接说明

更新时间：2026-09-23

## 项目概况

BeePlay（蜂玩）是一个手机端优先的互动小游戏与创作产品原型。当前版本以 `index.html` 为主要页面，使用原生 HTML、CSS 和 JavaScript 实现，不依赖后端服务即可直接打开预览。

## 当前页面与入口

- 首页：竖向游戏流，支持上下切换、播放/暂停、点赞、评论、收藏、分享和关注。
- 探索页：按分类浏览作品，支持进入 Remix 流程。
- 创作页：输入一句话生成游戏的前端演示。
- 创建入口：支持“从一个想法开始”“Remix 一个作品”“导入一个完成的小游戏”。
- 消息页：包含赞和收藏、新增关注、评论和@，以及 Bee、社群、系统消息和用户私聊入口。
- 个人主页：包含作品、点赞、收藏、浏览记录，以及作品删除、可见范围和“是否允许二创”设置。
- 导入页：支持选择 HTML 游戏压缩包或文件夹，并填写游戏名称、描述、分类、图标和封面颜色。

## 建议优先接入的后端能力

1. 用户与登录
   - 当前用户信息、头像、昵称、关注关系。
   - 推荐接口：`GET /api/me`、`PATCH /api/me`、`POST /api/users/:id/follow`。

2. 游戏作品
   - 游戏列表、分类、作品详情、游戏资源上传和发布。
   - 推荐接口：`GET /api/games`、`GET /api/games/:id`、`POST /api/games`、`POST /api/games/:id/remix`。
   - 导入小游戏时建议后端校验压缩包结构，并安全地解压到对象存储或静态资源服务。

3. 互动数据
   - 点赞、收藏、浏览量、评论、分享记录。
   - 推荐接口：`POST /api/games/:id/like`、`POST /api/games/:id/save`、`POST /api/games/:id/views`、`GET /api/games/:id/comments`、`POST /api/games/:id/comments`。

4. 消息与私聊
   - Bee、Cherry、Vitto、Alex 目前按传统用户聊天窗口展示。
   - 推荐数据结构：会话 `conversation`、消息 `message`、已读状态 `read_at`。
   - 推荐接口：`GET /api/conversations`、`GET /api/conversations/:id/messages`、`POST /api/conversations/:id/messages`、`POST /api/conversations/:id/read`。
   - 赞和收藏、新增关注、评论和@可以作为通知类型统一进入 `notifications` 表。

5. 作品权限
   - 当前原型支持：公开、仅自己可见、互关可见、粉丝可见。
   - “允许二创”需要和作品权限一起保存，例如：
     - `visibility`: `public` / `private` / `mutuals` / `followers`
     - `allow_remix`: `true` / `false`

## 建议的数据模型

### `users`

- `id`
- `nickname`
- `avatar_url`
- `bio`
- `created_at`

### `games`

- `id`
- `owner_id`
- `title`
- `description`
- `category`
- `cover_url`
- `game_url`
- `visibility`
- `allow_remix`
- `views_count`
- `likes_count`
- `created_at`
- `updated_at`

### `comments`

- `id`
- `game_id`
- `author_id`
- `content`
- `parent_id`
- `created_at`

### `conversations` / `messages`

- `conversations.id`
- `conversations.type`
- `messages.id`
- `messages.conversation_id`
- `messages.sender_id`
- `messages.content`
- `messages.read_at`
- `messages.created_at`

## 当前前端原型的限制

- 所有数据目前写在 `index.html` 的 JavaScript 中，刷新页面会恢复初始状态。
- 点赞、收藏、评论、回复消息、作品删除、可见范围和二创权限目前都是本地交互演示。
- 上传小游戏目前只记录前端选择结果，尚未真正上传或解析文件。
- 首页游戏流目前使用静态视觉场景，实际游戏资源需要由后端返回 `game_url` 或可嵌入的 HTML 资源地址。
- 当前没有登录鉴权、接口请求、错误重试和数据持久化。

## 接入建议

建议后端接入时保留现有页面结构和 `data-*` 行为标记，先把静态数组替换成接口返回的数据，再逐步把点击事件中的本地状态改为 API 请求。上传、评论、消息和权限接口完成后，再补充登录态、加载态、空状态和失败提示。

## 本地预览

直接打开 `index.html` 即可预览。资源路径以项目根目录为基准，请不要单独移动 `index.html` 或 `assets/` 文件夹。
