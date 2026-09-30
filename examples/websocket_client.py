import asyncio
import json

import websockets


async def main():
    async with websockets.connect("ws://127.0.0.1:8080/ws/events") as ws:
        while True:
            message = await ws.recv()
            print(json.loads(message))


if __name__ == "__main__":
    asyncio.run(main())
