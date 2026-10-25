"""Public snapshot bootstrap. A frozen archive is not a live provider."""
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
import re
import httpx
import numpy as np
import pandas as pd
from core.history import HistoryCatalog

STOCK_ARCHIVE='https://raw.githubusercontent.com/plotly/datasets/master/all_stocks_5yr.csv'

async def download(url,limit=100_000_000):
    async with httpx.AsyncClient(timeout=90,follow_redirects=True) as client:
        async with client.stream('GET',url) as response:
            response.raise_for_status()
            chunks=[];size=0
            async for chunk in response.aiter_bytes():
                size+=len(chunk)
                if size>limit: raise ValueError('download exceeds configured size limit')
                chunks.append(chunk)
            return b''.join(chunks)

def normalize_stock_archive(raw):
    f=pd.read_csv(BytesIO(raw)).rename(columns={'date':'timestamp','Name':'symbol'})
    required=['timestamp','symbol','open','high','low','close','volume']
    if not set(required)<=set(f): raise ValueError('unexpected archive schema')
    f=f[required].copy()
    f['timestamp']=pd.to_datetime(f.timestamp,utc=True,errors='coerce')
    numeric=['open','high','low','close','volume']
    for key in numeric:f[key]=pd.to_numeric(f[key],errors='coerce')
    valid=(f.timestamp.notna() & f.symbol.str.fullmatch(r'[A-Z][A-Z0-9.\-]{0,14}',na=False)
        & np.isfinite(f[numeric]).all(axis=1) & (f[['open','high','low','close']]>0).all(axis=1)
        & (f.volume>=0) & (f.low<=f[['open','close']].min(axis=1))
        & (f.high>=f[['open','close']].max(axis=1)) & (f.low<=f.high))
    rejected=f.loc[~valid].copy();accepted=f.loc[valid].copy()
    duplicates=accepted.duplicated(['symbol','timestamp'],keep=False)
    # Conflicting archive duplicates are quarantined, not arbitrarily overwritten.
    rejected=pd.concat([rejected,accepted.loc[duplicates]],ignore_index=True)
    accepted=accepted.loc[~duplicates]
    accepted['interval']='1d';accepted['source']='plotly_stock_archive'
    return accepted,rejected

async def bootstrap_stocks(store,cache_dir='data/raw'):
    raw=await download(STOCK_ARCHIVE)
    accepted,rejected=normalize_stock_archive(raw)
    catalog=HistoryCatalog(store)
    digest=catalog.provenance('plotly_stock_archive',STOCK_ARCHIVE,raw,len(accepted),len(rejected),{
       'universe':'static historical S&P 500 constituent snapshot; survivorship biased',
       'adjustments':'not verified; no total-return or corporate-action guarantees',
       'timestamps':'session-date labels at UTC midnight, not signal availability timestamps',
       'license':'See upstream plotly/datasets LICENSE and original data attribution before redistribution',
       'synthetic':False})
    root=Path(cache_dir);root.mkdir(parents=True,exist_ok=True)
    (root/f'{digest}.csv').write_bytes(raw)
    if not rejected.empty: rejected.to_csv(root/f'{digest}.quarantine.csv',index=False)
    store.upsert_frame(accepted)
    return {'sha256':digest,'rows':len(accepted),'rejected':len(rejected),'symbols':int(accepted.symbol.nunique()),'first':accepted.timestamp.min().isoformat(),'last':accepted.timestamp.max().isoformat(),'source':'plotly_stock_archive'}
