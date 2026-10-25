from abc import ABC, abstractmethod
from datetime import datetime
import asyncio
import httpx

class BaseDataIngestor(ABC):
    @abstractmethod
    async def fetch(self, symbol: str, start: datetime, end: datetime, interval: str): ...

async def get_json(url, *, params=None, headers=None, client=None):
    async def request(c):
        for attempt in range(4):
            response = await c.get(url, params=params, headers=headers)
            if response.status_code in (429,500,502,503,504) and attempt<3:
                await asyncio.sleep(min(float(response.headers.get("Retry-After", 2**attempt)),30))
                continue
            response.raise_for_status()
            return response.json()
    if client is not None:
        return await request(client)
    async with httpx.AsyncClient(timeout=30) as c:
        return await request(c)
