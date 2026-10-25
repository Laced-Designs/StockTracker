from pathlib import Path
from threading import RLock
from typing import Protocol
import json
import duckdb
from core.models import OHLCV, MarketTick, PredictionSignal

class TimeSeriesStore(Protocol):
    def upsert_bars(self, bars: list[OHLCV]) -> int: ...
    def bars(self, symbol: str, interval: str = "1m", limit: int = 20000): ...
    def close(self): ...

class DuckDBStore:
    """Single-process embedded store; all connection access is serialized."""
    def __init__(self, path: str):
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.lock = RLock()
        self.conn = duckdb.connect(path)
        self.conn.execute("""CREATE TABLE IF NOT EXISTS bars (
          symbol VARCHAR, timestamp TIMESTAMPTZ, interval VARCHAR,
          open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE, volume DOUBLE,
          source VARCHAR, PRIMARY KEY(symbol,timestamp,interval,source));
          CREATE TABLE IF NOT EXISTS ticks (
          source VARCHAR, trade_id VARCHAR, symbol VARCHAR, timestamp TIMESTAMPTZ,
          price DOUBLE, size DOUBLE, side VARCHAR, PRIMARY KEY(source,trade_id));
          CREATE TABLE IF NOT EXISTS events (
          source VARCHAR, event_id VARCHAR, available_at TIMESTAMPTZ,
          payload JSON, PRIMARY KEY(source,event_id));
          CREATE TABLE IF NOT EXISTS signals (
          symbol VARCHAR, timestamp TIMESTAMPTZ, payload JSON);
        """)
    def upsert_bars(self, bars):
        rows = [[b.symbol,b.timestamp,b.interval,b.open,b.high,b.low,b.close,b.volume,b.source] for b in bars]
        if rows:
            with self.lock:
                self.conn.execute("BEGIN")
                try:
                    self.conn.executemany("INSERT OR REPLACE INTO bars VALUES (?,?,?,?,?,?,?,?,?)", rows)
                    self.conn.execute("COMMIT")
                except Exception:
                    self.conn.execute("ROLLBACK")
                    raise
        return len(rows)
    def bars(self, symbol, interval="1m", limit=20000, source=None):
        # Do not silently splice providers or synthetic and real data.
        with self.lock:
            if source is None:
                sources = self.conn.execute("SELECT DISTINCT source FROM bars WHERE symbol=? AND interval=?", [symbol,interval]).fetchall()
                if len(sources)>1:
                    raise ValueError("multiple sources present; specify source")
                source = sources[0][0] if sources else ""
            if limit is None:
                return self.conn.execute("SELECT * FROM bars WHERE symbol=? AND interval=? AND source=? ORDER BY timestamp",[symbol,interval,source]).df()
            return self.conn.execute("""SELECT * FROM (SELECT * FROM bars
                WHERE symbol=? AND interval=? AND source=? ORDER BY timestamp DESC LIMIT ?)
                ORDER BY timestamp""", [symbol,interval,source,limit]).df()
    def upsert_frame(self,frame):
        """Vectorized validated bulk import; identical source keys remain idempotent."""
        columns=['symbol','timestamp','interval','open','high','low','close','volume','source']
        if frame.empty: return 0
        with self.lock:
            self.conn.register('_incoming_bars',frame[columns])
            try:
                self.conn.execute('INSERT OR REPLACE INTO bars SELECT * FROM _incoming_bars')
            finally:
                self.conn.unregister('_incoming_bars')
        return len(frame)
    def tick(self, tick: MarketTick):
        with self.lock:
            result=self.conn.execute("INSERT OR IGNORE INTO ticks VALUES (?,?,?,?,?,?,?) RETURNING trade_id", [tick.source,tick.trade_id,tick.symbol,tick.timestamp,tick.price,tick.size,tick.side]).fetchone()
            return result is not None
    def event(self, source, event_id, available_at, payload):
        with self.lock:
            self.conn.execute("INSERT OR REPLACE INTO events VALUES (?,?,?,?)", [source,event_id,available_at,json.dumps(payload)])
    def signal(self, signal: PredictionSignal):
        with self.lock:
            self.conn.execute("INSERT INTO signals VALUES (?,?,?)", [signal.symbol,signal.timestamp,signal.model_dump_json()])
    def aggregate(self, symbol, minutes=15, source=None):
        if minutes not in (15,60,1440):
            raise ValueError("supported buckets: 15,60,1440")
        frame=self.bars(symbol, source=source)
        if frame.empty:
            return frame
        return frame.set_index("timestamp").resample(f"{minutes}min", label="left", closed="left").agg(
            {"open":"first","high":"max","low":"min","close":"last","volume":"sum"}).dropna()
    def close(self):
        with self.lock:
            self.conn.close()
