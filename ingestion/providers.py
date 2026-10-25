from datetime import datetime, timezone
from urllib.parse import quote
from zoneinfo import ZoneInfo
from core.models import OHLCV
from ingestion.base import BaseDataIngestor, get_json

class YahooFinanceIngestor(BaseDataIngestor):
    async def fetch_max_daily(self,symbol):
        data=await get_json(f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(symbol,safe='')}",params={"range":"max","interval":"1d"},headers={"User-Agent":"MarketPulse/0.2"})
        return self.parse(data,symbol,"1d")
    @staticmethod
    def parse(data,symbol,interval):
        if data["chart"].get("error"): raise ValueError(str(data["chart"]["error"]))
        result=data["chart"]["result"][0]
        q=result["indicators"]["quote"][0]
        rows=[]
        for i,t in enumerate(result.get("timestamp",[])):
            values={k:q[k][i] for k in ("open","high","low","close","volume")}
            if any(v is None for v in values.values()): continue
            rows.append(OHLCV(symbol=symbol,timestamp=datetime.fromtimestamp(t,timezone.utc),interval=interval,source="yahoo",**values))
        return rows
    async def fetch(self, symbol, start, end, interval="1d"):
        if start.tzinfo is None or end.tzinfo is None or start>=end:
            raise ValueError("ordered aware timestamps required")
        data=await get_json(f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(symbol, safe='')}",
            params={"period1":int(start.timestamp()),"period2":int(end.timestamp()),"interval":"60m" if interval=="1h" else interval},headers={"User-Agent":"MarketPulse/0.1"})
        return self.parse(data,symbol,interval)

class AlphaVantageIngestor(BaseDataIngestor):
    def __init__(self,key):
        if not key: raise ValueError("Alpha Vantage key required")
        self.key=key
    async def fetch(self,symbol,start,end,interval="1d"):
        if interval not in ("1d","1m","15m","1h"):
            raise ValueError("unsupported interval")
        if start.tzinfo is None or end.tzinfo is None or start>=end:
            raise ValueError("ordered aware timestamps required")
        params={"function":"TIME_SERIES_DAILY" if interval=="1d" else "TIME_SERIES_INTRADAY", "symbol":symbol,"apikey":self.key,"outputsize":"full"}
        if interval!="1d": params["interval"]={"1m":"1min","15m":"15min","1h":"60min"}[interval]
        data=await get_json("https://www.alphavantage.co/query",params=params)
        key=next((k for k in data if k.startswith("Time Series")),None)
        if key is None:
            raise ValueError("Alpha Vantage returned no time series (check entitlement, rate limit, symbol)")
        meta=data.get("Meta Data",{})
        tz=ZoneInfo(next((v for k,v in meta.items() if "Time Zone" in k),"America/New_York"))
        bars=[]
        for t,v in data[key].items():
            stamp=datetime.fromisoformat(t).replace(tzinfo=tz).astimezone(timezone.utc)
            if start<=stamp<end:
                bars.append(OHLCV(symbol=symbol,timestamp=stamp,interval=interval,source="alpha_vantage",**{name:float(v[f"{i}. {name}"]) for i,name in enumerate(("open","high","low","close","volume"),1)}))
        return sorted(bars,key=lambda b:b.timestamp)

class SECDataIngestor:
    """Recent company filing metadata, stored at acceptance time, never period end."""
    def __init__(self,user_agent):
        if "@" not in user_agent: raise ValueError("SEC requires an identifying User-Agent with contact email")
        self.user_agent=user_agent
    async def harvest(self,cik,store):
        cik=str(cik)
        if not cik.isdigit() or len(cik)>10: raise ValueError("invalid CIK")
        data=await get_json(f"https://data.sec.gov/submissions/CIK{int(cik):010d}.json",headers={"User-Agent":self.user_agent})
        r=data.get("filings",{}).get("recent",{})
        count=0
        for i,accession in enumerate(r.get("accessionNumber",[])):
            accepted=r["acceptanceDateTime"][i]
            stamp=datetime.fromisoformat(accepted.replace("Z","+00:00"))
            if stamp.tzinfo is None: stamp=stamp.replace(tzinfo=timezone.utc)
            store.event("sec",accession,stamp,{"cik":cik,"form":r["form"][i],"document":r["primaryDocument"][i],"accepted":accepted})
            count+=1
        return count

class FREDIngestor:
    """ALFRED vintage observations preserve first-publication availability dates."""
    def __init__(self,key): self.key=key
    async def harvest(self,series_id,store):
        data=await get_json("https://api.stlouisfed.org/fred/series/observations",params={"series_id":series_id,"api_key":self.key,"file_type":"json","output_type":4,"realtime_start":"1776-07-04","realtime_end":"9999-12-31"})
        for row in data.get("observations",[]):
            store.event("fred",f"{series_id}:{row['date']}:{row['realtime_start']}",datetime.fromisoformat(row["realtime_start"]).replace(tzinfo=timezone.utc),row|{"series":series_id,"availability_precision":"day; do not use intraday"})
        return len(data.get("observations",[]))
