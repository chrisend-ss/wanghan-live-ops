import os
import requests

API_URL = os.getenv("LIVE_OPS_URL", "http://127.0.0.1:8080/ingest")
API_KEY = os.getenv("LIVE_OPS_API_KEY", "change-me")

payload = {
    "type": "chat",
    "room_id": "WANGHAN_ROOM",
    "user_id": "demo-user",
    "nickname": "焓门观众",
    "content": "测试弹幕",
    "metadata": {},
}

resp = requests.post(
    API_URL,
    json=payload,
    headers={"X-API-Key": API_KEY},
    timeout=10,
)
print(resp.status_code, resp.json())
