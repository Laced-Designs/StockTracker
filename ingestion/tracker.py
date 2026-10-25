"""Single-process harvest loop. Run separately from a DuckDB-backed API server."""
import asyncio
from datetime import datetime,timezone
from ingestion.backfill import DEFAULT_STOCKS,plan,run_jobs

async def track(store,*,cycles=1,interval_seconds=3600,budget=20,stocks=None):
    if cycles<0 or interval_seconds<1 or budget<1:raise ValueError('positive interval/budget and nonnegative cycles required')
    count=0
    while cycles==0 or count<cycles:
        with store.lock:
            known=[row[0] for row in store.conn.execute("SELECT DISTINCT symbol FROM bars WHERE source!='synthetic'").fetchall()]
        universe=sorted(set(DEFAULT_STOCKS+known)) if stocks is None else stocks
        # A fixed UTC-day boundary makes planning idempotent within each day.
        now=datetime.now(timezone.utc).replace(hour=0,minute=0,second=0,microsecond=0)
        planned=plan(store,stocks=universe,now=now)
        result=await run_jobs(store,limit=budget)
        print({'cycle':count+1,'planned':planned,'completed_jobs':len(result)},flush=True)
        count+=1
        if cycles and count>=cycles:break
        await asyncio.sleep(interval_seconds)
