"""Daily reference prices from Coin Metrics community archives, not fake OHLCV."""
from io import BytesIO
from pathlib import Path
import pandas as pd
from core.history import HistoryCatalog
from ingestion.archive import download

async def bootstrap_crypto(store,assets=('BTC','ETH','SOL'),cache_dir='data/raw'):
    catalog=HistoryCatalog(store);results=[]
    with store.lock:
        store.conn.execute("CREATE TABLE IF NOT EXISTS price_observations (source VARCHAR,symbol VARCHAR,timestamp TIMESTAMPTZ,price DOUBLE,PRIMARY KEY(source,symbol,timestamp))")
    for asset in assets:
        if not asset.isalpha() or not asset.isupper():raise ValueError('invalid crypto asset')
        url=f'https://raw.githubusercontent.com/coinmetrics/data/master/csv/{asset.lower()}.csv'
        raw=await download(url)
        header=pd.read_csv(BytesIO(raw),nrows=0).columns
        field='PriceUSD' if 'PriceUSD' in header else 'ReferenceRateUSD'
        f=pd.read_csv(BytesIO(raw),usecols=['time',field]).rename(columns={'time':'timestamp',field:'price'})
        f['timestamp']=pd.to_datetime(f.timestamp,utc=True,errors='coerce');f['price']=pd.to_numeric(f.price,errors='coerce')
        good=f.timestamp.notna() & f.price.notna() & (f.price>0) & (f.price<float('inf'))
        rejected=int((~good).sum());f=f.loc[good].drop_duplicates('timestamp').copy()
        f['source']='coinmetrics_reference';f['symbol']=asset+'-USD'
        digest=catalog.provenance('coinmetrics_reference',url,raw,len(f),rejected,{
            'asset_class':'crypto','field':field+' daily USD price metric, not a venue candle',
            'license':'Coin Metrics community data terms and upstream attribution apply',
            'timestamps':'provider day labels; precise historical publication times not verified',
            'synthetic':False})
        root=Path(cache_dir);root.mkdir(parents=True,exist_ok=True);(root/f'{digest}.csv').write_bytes(raw)
        with store.lock:
            store.conn.register('_prices',f[['source','symbol','timestamp','price']])
            try:store.conn.execute('INSERT OR REPLACE INTO price_observations SELECT * FROM _prices')
            finally:store.conn.unregister('_prices')
        results.append({'symbol':asset+'-USD','observations':len(f),'rejected':rejected,'first':f.timestamp.min().isoformat(),'last':f.timestamp.max().isoformat(),'sha256':digest})
    return results
