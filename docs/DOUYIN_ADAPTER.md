# 抖音采集适配器

本仓库不直接内置第三方抖音逆向采集代码，而是用 adapter 将采集器输出转成 WangHan Live Ops 的标准事件。

## 推荐结构

```text
第三方/自建抖音采集器
      │ stdout
      ▼
douyin_stdout_adapter.py
      │ HTTP
      ▼
POST /ingest
      │
      ├─ /stats
      ├─ /events/recent
      └─ /ws/events
```

## 环境变量

```bash
LIVE_OPS_URL=http://127.0.0.1:8080/ingest
LIVE_OPS_API_KEY=change-me
DOUYIN_ROOM_ID=王焓直播间ID
```

## 使用

如果采集程序将事件打印到标准输出：

```bash
python your_douyin_collector.py | python adapters/douyin_stdout_adapter.py
```

适配器当前识别这些常见文本：

- `【聊天msg】...`
- `【进场msg】...`
- `【点赞msg】...`
- `【礼物msg】...`
- `【粉丝团msg】...`
- `【统计msg】当前观看人数..., 累计观看人数...`

## 为什么不把第三方采集器直接拷进来

1. 抖音页面、签名与协议可能变化；
2. 某些项目许可证要求不同；
3. 登录 Cookie、验证码和账号状态应该与运营 API 隔离；
4. 更换采集实现时，不影响你的实时数据面板和复盘逻辑。
