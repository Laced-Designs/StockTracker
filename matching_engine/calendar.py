from datetime import datetime,timezone
import exchange_calendars as xcals
import pandas as pd

def market_status(now=None):
    now=now or datetime.now(timezone.utc)
    try:
        cal=xcals.get_calendar('XNYS');minute=pd.Timestamp(now).floor('min')
        opened=bool(cal.is_open_on_minute(minute))
        return {'open':opened,'exchange':'NYSE','asof':now.isoformat(),'reason':'Regular session' if opened else 'Outside regular session / holiday'}
    except Exception:return {'open':False,'exchange':'NYSE','asof':now.isoformat(),'reason':'Calendar unavailable; execution paused'}
