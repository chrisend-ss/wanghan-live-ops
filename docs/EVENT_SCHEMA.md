# Event schema

所有采集器统一转换为以下事件模型后再写入 `POST /ingest`。

## chat
```json
{
  "type": "chat",
  "room_id": "123",
  "user_id": "u1",
  "nickname": "viewer",
  "content": "今晚好听",
  "metadata": {}
}
```

## enter
```json
{
  "type": "enter",
  "room_id": "123",
  "user_id": "u2",
  "nickname": "new viewer",
  "metadata": {}
}
```

## like
```json
{
  "type": "like",
  "room_id": "123",
  "user_id": "u3",
  "nickname": "viewer",
  "count": 9,
  "metadata": {}
}
```

## gift
```json
{
  "type": "gift",
  "room_id": "123",
  "user_id": "u4",
  "nickname": "viewer",
  "content": "粉丝团灯牌",
  "count": 1,
  "value": 0,
  "metadata": {
    "gift_name": "粉丝团灯牌"
  }
}
```

## audience_stats
```json
{
  "type": "audience_stats",
  "room_id": "123",
  "metadata": {
    "current_audience": 22140,
    "total_viewers": 436000
  }
}
```
