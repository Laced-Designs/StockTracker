"""Durable harvest ledger, source provenance, coverage and research results."""
from datetime import datetime, timezone
import hashlib
import json
import uuid
import pandas as pd

class HistoryCatalog:
    def __init__(self,store):
        self.store=store
        with store.lock:
            store.conn.execute("""
            CREATE TABLE IF NOT EXISTS price_observations (source VARCHAR,symbol VARCHAR,timestamp TIMESTAMPTZ,price DOUBLE,PRIMARY KEY(source,symbol,timestamp));
            CREATE TABLE IF NOT EXISTS harvest_jobs (
              id VARCHAR PRIMARY KEY, provider VARCHAR, symbol VARCHAR, interval VARCHAR,
              start_at TIMESTAMPTZ, end_at TIMESTAMPTZ, status VARCHAR,
              attempts INTEGER, rows_written BIGINT, error VARCHAR, updated_at TIMESTAMPTZ);
            CREATE TABLE IF NOT EXISTS provenance (
              sha256 VARCHAR PRIMARY KEY, source VARCHAR, url VARCHAR,
              retrieved_at TIMESTAMPTZ, bytes BIGINT, accepted BIGINT, rejected BIGINT, details JSON);
            CREATE TABLE IF NOT EXISTS research_runs (
              id VARCHAR PRIMARY KEY, created_at TIMESTAMPTZ, report JSON);
            """)
    def enqueue(self,provider,symbol,interval,start,end):
        raw=f"{provider}|{symbol}|{interval}|{start.isoformat()}|{end.isoformat()}"
        key=hashlib.sha256(raw.encode()).hexdigest()[:24]
        with self.store.lock:
            self.store.conn.execute("INSERT OR IGNORE INTO harvest_jobs VALUES (?,?,?,?,?,?,'pending',0,0,NULL,?)",[key,provider,symbol,interval,start,end,datetime.now(timezone.utc)])
        return key
    def jobs(self):
        with self.store.lock:
            return self.store.conn.execute("SELECT * FROM harvest_jobs ORDER BY updated_at,id").df()
    def mark(self,key,status,rows=0,error=None):
        with self.store.lock:
            self.store.conn.execute("UPDATE harvest_jobs SET status=?, attempts=attempts+?, rows_written=?, error=?, updated_at=? WHERE id=?",[status,int(status=='running'),rows,error,datetime.now(timezone.utc),key])
    def provenance(self,source,url,raw,accepted,rejected,details):
        digest=hashlib.sha256(raw).hexdigest()
        with self.store.lock:
            self.store.conn.execute("INSERT OR REPLACE INTO provenance VALUES (?,?,?,?,?,?,?,?)",[digest,source,url,datetime.now(timezone.utc),len(raw),accepted,rejected,json.dumps(details)])
        return digest
    def coverage(self):
        with self.store.lock:
            f=self.store.conn.execute("""WITH observed AS (
               SELECT source,symbol,interval,timestamp,volume FROM bars
               UNION ALL SELECT source,symbol,'1d' AS interval,timestamp,NULL AS volume FROM price_observations
            ), gaps AS (SELECT *, extract(epoch FROM timestamp-lag(timestamp) OVER (PARTITION BY source,symbol,interval ORDER BY timestamp))/86400 AS gap_days FROM observed)
            SELECT source,symbol,interval,count(*) AS observations,
               min(timestamp) AS first_bar,max(timestamp) AS last_bar,
               count(*) FILTER (WHERE volume=0) AS zero_volume_bars,
               max(gap_days) AS largest_observed_gap_days,
               count(*) FILTER (WHERE gap_days>4) AS gaps_over_four_days
               FROM gaps GROUP BY source,symbol,interval ORDER BY source,symbol,interval""").df()
        now=pd.Timestamp.now(tz='UTC')
        if not f.empty:
            f['staleness_days']=(now-f.last_bar).dt.total_seconds()/86400
        return f.astype(object).where(f.notna(),None)
    def save_report(self,report):
        key=uuid.uuid4().hex
        with self.store.lock:
            self.store.conn.execute("INSERT INTO research_runs VALUES (?,?,?)",[key,datetime.now(timezone.utc),json.dumps(report,allow_nan=False)])
        return key
    def latest_report(self):
        with self.store.lock:
            row=self.store.conn.execute("SELECT report FROM research_runs ORDER BY created_at DESC LIMIT 1").fetchone()
        return json.loads(row[0]) if row else None
