"""Reproducible offline research artifact; never advances live or paper accounts."""
import json
from pathlib import Path
from datetime import datetime,timezone
from data_ingestion.mock import generate,events
from models.predictor import Predictor,correlate

def main():
    result={'created_at':datetime.now(timezone.utc).isoformat(),'mode':'synthetic_offline_calibration','instruments':{}}
    for symbol in ['AAPL','MSFT','NVDA','SPY','AMZN','TSLA']:
        bars=generate(symbol);news=events(bars,symbol)
        result['instruments'][symbol]={'prediction':Predictor().predict(bars,news,demo=True),'event_association':correlate(bars,news)}
    Path('artifacts').mkdir(exist_ok=True);Path('artifacts/offline-research.json').write_text(json.dumps(result,indent=2));print('Saved artifacts/offline-research.json · synthetic calibration only')
if __name__=='__main__':main()
