import asyncio
from fastapi.testclient import TestClient
from api.main import create_app
from core.config import Settings


def test_overview_privacy_empty_trades_and_disabled_collectors(tmp_path):
    app=create_app(Settings(database_path=str(tmp_path/'ui.duckdb'),demo=False))
    with TestClient(app) as client:
        response=client.post('/api/paper/accounts',json={'name':'Private account','mode':'live','initial_tokens':777})
        assert response.status_code==201
        account=response.json()
        result=client.get('/api/overview')
        assert result.status_code==200
        data=result.json()
        assert data['collection_status']=='Disabled'
        assert data['feed_status']=='No fresh eligible quotes'
        assert len(data['leaderboard'])==1
        row=data['leaderboard'][0]
        assert row['status']=='Not started' and row['fills']==0
        assert float(row['equity_tokens'])==500
        assert data['activity']==[]
        assert account['access_key'] not in result.text
        assert account['account']['id'] not in result.text
        assert 'Private account' not in result.text
        for path in ['/','/tasks','/reports','/bugs']:
            assert client.get(path).status_code==200
        assert 'Drafts stay in this browser' in client.get('/bugs').text


def test_overview_detects_stopped_background_task(tmp_path):
    app=create_app(Settings(database_path=str(tmp_path/'ui.duckdb'),demo=False))
    with TestClient(app) as client:
        async def stopped():pass
        # A completed task must not appear as a running collector.
        async def install():
            task=asyncio.create_task(stopped())
            await task
            app.state.collectors['study']=task
        client.portal.call(install)
        assert client.get('/api/overview').json()['collection_status']=='Stopped'
