# WangHan Live Ops Hub

面向王焓直播运营的数据与策略中枢。目标是把直播侧事件、录屏复盘、运营部门审查和长期实验统一到一套可追踪的系统里。

## 个人运营 Skill：新分支核心运营思路

当前版本：**0.3.2**

统一入口已整合王焓直播复盘：证据核验→可信时间轴→漏斗分析→战略审查→下一轮实验。当前优先提高进房与新人留存。

该 Skill 现在包含四层：
- **战略层**：八大战略模块 + 进房/留人/关系/消费/扩散
- **运营部门审查层**：证据等级、真人一致性、包装倒灌、关系边界、数据归因与执行风险
- **插件工具层**：wanghan-live-review、GitHub、Google Drive、Files/Library、Web/Deep Research、可选 vidIQ
- **数据闭环**：变量 → 指标 → 验证 → 审查 → 结论 → 下一轮实验

默认先画面/进房，再内容承接、人群粘性和二创放大，每日复盘贯穿全程；默认不写主播具体话术。

核心文件：
- [SKILL.md](skills/wanghan-core-ops/SKILL.md)
- [运营部门审查规则](skills/wanghan-core-ops/references/operations-department.md)
- [指标口径](skills/wanghan-core-ops/references/measurement.md)
- [调用示例](skills/wanghan-core-ops/references/examples.md)

调用标识：`$wanghan-core-ops`
中文展示名：**新分支核心运营思路**

## B站录屏与Chrome后台数据入口

B站链接/BV可读取视频身份、分P/CID和字幕轨线索，优先复用同分P已有转写；匿名接口失败时从正常浏览器页面只读取得元数据。旧字幕不自动认定为王焓原话。云端转写沿用已有工作流，不因本次升级重跑历史任务。

抖音后台使用用户已登录的Chrome配置，通过宿主官方扩展连接。先核对账号、场次与筛选，再读取原生导出/页面数值；当前工具允许开发者读取时可核对已观察的JSON趋势响应。后台页面未实际连接和采集前，不宣称取得数据。

- [两个入口的完整流程与Chrome安装入口](skills/wanghan-core-ops/references/source-acquisition.md)
- [只读元数据/指标整理脚本](skills/wanghan-core-ops/scripts/prepare_sources.py)
- [后台交接格式（全部虚构）](skills/wanghan-core-ops/references/backend-capture-example.json)

```bash
python skills/wanghan-core-ops/scripts/prepare_sources.py bilibili --url "https://www.bilibili.com/video/BV1TPaf6tEJi/" --reviews-root reviews --output data/bilibili-intake.json
python skills/wanghan-core-ops/scripts/prepare_sources.py backend --input data/capture.json --output data/normalized.json
```

脚本不读取浏览器凭据、不自动连接抖音、不下载媒体或启动转写。后台整理保留单位、增量/累计/瞬时口径、窗口与缺失；认证参数不保存，比例需另行审查后计算。真实场次结果只存私人台账。

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
dashboard / Drive / ChatGPT / 核心运营Skill
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

## 数据合规

只采集运营所需的直播事件；不要把登录 Cookie、账号密码、App Secret、长期 token 或可识别粉丝个人身份的后台原始数据提交到 GitHub。生产环境请使用环境变量或密钥管理服务。
