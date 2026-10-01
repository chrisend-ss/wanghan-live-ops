# WangHan Live Ops Hub

面向王焓直播运营的数据接口层。目标是把直播侧事件统一为一个稳定的本地/服务器 API，供实时面板、飞书、ChatGPT 分析和直播复盘使用。

## 个人运营 Skill：新分支核心运营思路

新增可复用的八大战略模块Skill，以直播数据验证视觉、内容与活动。默认先画面/进房，再内容承接、人群粘性和二创放大，每日复盘贯穿全程；默认不写主播具体话术。

查看 [Skill说明、安装与调用示例](docs/CORE_OPS_SKILL.md) 或直接阅读 [SKILL.md](skills/wanghan-core-ops/SKILL.md)。调用标识：`$wanghan-core-ops`，中文展示名：**新分支核心运营思路**。

## 当前能力

- REST 健康检查：`GET /health`
- 事件写入：`POST /ingest`
- 最近事件：`GET /events/recent`
- 实时 WebSocket：`/ws/events`
- 实时统计：`GET /stats`
- 支持事件类型：
  - `chat` 弹幕
  - `enter` 进房
  - `like` 点赞
  - `gift` 礼物
  - `fanclub` 粉丝团
  - `audience_stats` 当前/累计观看
  - `follow` 关注
  - `system` 其他系统事件

## 设计原则

采集层与接口层分离。抖音页面或协议变化时，只替换采集器，不影响飞书、ChatGPT、数据面板等下游。

```text
Douyin live room
      ↓
collector / adapter
      ↓
POST /ingest
      ↓
WangHan Live Ops Hub
  ├─ REST API
  ├─ WebSocket
  ├─ rolling stats
  └─ recent event buffer
      ↓
dashboard / Feishu / ChatGPT
```

## 启动

需要 Python 3.10+。

```bash
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS/Linux
source .venv/bin/activate

pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload
```

启动后：

- Swagger: http://127.0.0.1:8080/docs
- Health: http://127.0.0.1:8080/health
- Stats: http://127.0.0.1:8080/stats
- WebSocket: ws://127.0.0.1:8080/ws/events

## 写入事件示例

```bash
curl -X POST http://127.0.0.1:8080/ingest \
  -H "Content-Type: application/json" \
  -H "X-API-Key: change-me" \
  -d '{
    "type": "chat",
    "room_id": "WANGHAN_ROOM",
    "user_id": "123",
    "nickname": "焓门观众",
    "content": "今晚这首歌好听",
    "metadata": {}
  }'
```

如果 `.env` 里的 `LIVE_OPS_API_KEY` 留空，则本地调试时不校验 API Key。

## 下一步接抖音采集

本仓库先提供稳定接口层，不直接复制第三方逆向代码。推荐把抖音采集器作为独立进程运行，再将标准化事件 POST 到 `/ingest`。

这样可以：
1. 避免采集协议变化拖垮整个系统；
2. 独立处理 Cookie/验证码等敏感信息；
3. 后续替换成官方或更稳定的数据源时，下游不需要改。

## 数据合规

只采集运营所需的直播事件；不要把登录 Cookie、账号密码、App Secret 或长期 token 提交到 GitHub。生产环境请使用环境变量或密钥管理服务。
