from datetime import datetime,timedelta,timezone
from decimal import Decimal
import json
import numpy as np
import pandas as pd
import pytest
from core.db import DuckDBStore
from paper.week_study import WeekStudy
from paper.models import Quote
from paper.option_tests import option_path


def test_calendar_week_model_expiry_cash_and_vega():
    dates=pd.bdate_range('2026-01-01',periods=80,tz='UTC')
    frame=pd.DataFrame({'timestamp':dates,'close':100.})
    start=next(i for i in range(30,50) if dates[i].weekday()==4)
    base=option_path(frame,start,'call',0)
    up=option_path(frame,start,'call',.10)
    assert base['whole_contracts']==int(base['whole_contracts'])
    assert Decimal(base['funding_spent_tokens'])<=500
    assert Decimal(base['cash_remaining_tokens'])>=0
    assert datetime.fromisoformat(base['valuation_time'])<=datetime.fromisoformat(base['window_ends'])
    assert datetime.fromisoformat(base['window_ends'])-dates[start].to_pydatetime()==timedelta(days=7)
    assert base['curve'][-1]['days_remaining']>0
    assert Decimal(up['ending_model_tokens'])>Decimal(base['ending_model_tokens'])
    assert Decimal(base['ending_model_tokens'])<500  # flat underlying: time decay and modeled costs
    assert base['mode']=='hypothetical_model_based_not_quoted_options'


def test_no_fractional_unaffordable_options_or_future_funding():
    f=pd.DataFrame({'timestamp':pd.date_range('2026-01-01',periods=70,tz='UTC'),'close':1_000_000.})
    result=option_path(f,35,'call',0)
    assert result['whole_contracts']==0 and result['ending_model_tokens']=='500.00000000'
    assert result['status']=='skipped_unaffordable_whole_contract'
    varied=pd.DataFrame({'timestamp':pd.date_range('2026-01-01',periods=70,tz='UTC'),'close':100*np.exp(np.arange(70)*.001)})
    original=option_path(varied,35,'put',0)
    varied.loc[37:,'close']*=.8
    changed=option_path(varied,35,'put',0)
    assert original['whole_contracts']==changed['whole_contracts']
    assert original['funding_spent_tokens']==changed['funding_spent_tokens']
    assert original['entry_realized_volatility_not_observed_iv']==changed['entry_realized_volatility_not_observed_iv']


def test_checkpoint_does_not_fast_forward_or_fabricate_trades():
    s=DuckDBStore(':memory:');clock=[None]
    # Plan clock is injected only for unit testing; CLI and API use server UTC.
    from pathlib import Path
    plan=json.loads(Path('paper/study_plan.json').read_text());start=datetime.fromisoformat(plan['created_at']);clock[0]=start+timedelta(seconds=5)
    study=WeekStudy(s,clock=lambda:clock[0])
    try:
        first=study.checkpoint();study.checkpoint()
        assert first['day']==0 and first['quoted_option_fills']==0
        assert study.status()['days_recorded']==[0]
        assert study.status()['spot_arms']==[]
        end=datetime.fromisoformat(plan['ends_at'])
        assert (end-start).total_seconds()==169*3600
        clock[0]=end-timedelta(minutes=20)
        assert 7 not in study.status()['missing_due_days']
        clock[0]=end+timedelta(seconds=1)
        assert study.checkpoint()['day']==7
        assert study.status()['missing_due_days']==[1,2,3,4,5,6]
    finally:s.close()


def test_spot_arms_require_next_quote_and_leave_original_challenge_untouched():
    s=DuckDBStore(':memory:')
    from pathlib import Path
    plan=json.loads(Path('paper/study_plan.json').read_text());clock=[datetime.fromisoformat(plan['created_at'])+timedelta(seconds=10)]
    study=WeekStudy(s,clock=lambda:clock[0]);e=study.exchange
    e.ensure_challenge(datetime(2026,10,25,17,15,32,tzinfo=timezone.utc))
    try:
        quote=Quote(symbol='BTC-USD',source='coinbase_public',market_time=clock[0],observed_at=clock[0],bid='100',ask='101',mode='live')
        e.publish(quote);orders=study.manage_spot()
        assert len(orders)==2 and all(o['status']=='pending' for o in orders)
        assert study.manage_spot()==[]
        clock[0]+=timedelta(seconds=1);e.publish(quote.model_copy(update={'market_time':clock[0],'observed_at':clock[0]}))
        arms=study.arm_status();assert len(arms)==4
        assert sum(a['filled_orders'] for a in arms)==2
        assert e.get('seven-day-agent')['cash_tokens']=='500.00000000'
        assert e.orders('seven-day-agent')==[]
    finally:s.close()


def test_stock_exit_before_weekend_waits_for_a_real_next_quote():
    from pathlib import Path
    plan=json.loads(Path('paper/study_plan.json').read_text())
    exit_time=datetime.fromisoformat(plan['precommitted_exits']['SPY']);clock=[exit_time-timedelta(minutes=5)]
    s=DuckDBStore(':memory:');study=WeekStudy(s,clock=lambda:clock[0]);e=study.exchange
    def stock_quote():return Quote(symbol='SPY',source='alpaca_iex',market_time=clock[0],observed_at=clock[0],bid='100',ask='100',mode='live')
    try:
        e.publish(stock_quote());assert len(study.manage_spot())==2
        clock[0]+=timedelta(seconds=1);e.publish(stock_quote())
        clock[0]=exit_time;e.publish(stock_quote());exits=study.manage_spot()
        assert len(exits)==2 and all(o['order']['side']=='sell' and o['status']=='pending' for o in exits)
        clock[0]+=timedelta(seconds=1);e.publish(stock_quote())
        assert study.manage_spot()==[]
        assert all(not a['valuation']['positions'] for a in study.arm_status())
    finally:s.close()
