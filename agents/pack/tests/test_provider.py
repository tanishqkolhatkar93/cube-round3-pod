"""Exercise the actual transport worker and parent deadline/accounting protocol."""
import time
import pytest
import httpx
from agents import bounded_provider


class Channel:
    def __init__(self):self.events=[]
    def send(self,event):self.events.append(event)
    def close(self):pass


@pytest.mark.parametrize('failure',[None,'call','cleanup','both','malformed','overflow'])
def test_worker_records_work_before_failure_and_sanitizes(monkeypatch,failure):
    channel=Channel()
    class Client:
        def __init__(self,**kwargs):assert kwargs['follow_redirects'] is False
        def post(self,url,**kwargs):
            assert kwargs['headers']['X-goog-api-key']=='test-key'
            if failure in ('call','both'):raise RuntimeError('SECRET raw upstream diagnostic')
            class Response:
                def raise_for_status(self):pass
                def json(self):return {'modelVersion':'actual-model-123','candidates':[{'finishReason':'STOP',
                    'content':{'parts':[{'text':'not json' if failure=='malformed' else '{"value":1e999}' if failure=='overflow' else '{"images":[]}'}]}}]}
            return Response()
        def close(self):
            if failure in ('cleanup','both'):raise RuntimeError('SECRET cleanup diagnostic')
    monkeypatch.setattr(httpx,'Client',Client)
    bounded_provider.worker(channel,{'model':'chosen-model','deadline_s':1},'test-key','facts',{},[])
    assert channel.events[0]=={'event':'attempt','model':'chosen-model'}
    assert len([e for e in channel.events if e['event']=='attempt'])==1
    if failure not in ('call','both'):
        assert channel.events[1]=={'event':'accounting','version':'actual-model-123'}
    result=channel.events[-1]
    expected={'call':'provider_unavailable','both':'provider_unavailable','cleanup':'provider_cleanup_failure','malformed':'invalid_provider_response','overflow':'invalid_provider_response'}
    assert result.get('error')==expected.get(failure)
    assert 'SECRET' not in str(channel.events)


def slow_worker(connection,selection,key,prompt,payload,images):
    connection.send({'event':'attempt','model':selection['model']})
    connection.send({'event':'accounting','version':'completed-before-cleanup'})
    time.sleep(30)


def test_parent_kills_worker_and_preserves_accounting(monkeypatch):
    monkeypatch.setenv('POD_TEST_KEY','not-a-real-key')
    monkeypatch.setattr(bounded_provider,'worker',slow_worker)
    stats={'calls':0,'attempts':[]};start=time.monotonic()
    response,code=bounded_provider.invoke({'model':'test-model','api_key_env':'POD_TEST_KEY','deadline_s':3},'facts',{},[],stats)
    assert code=='provider_timeout' and response is None
    assert time.monotonic()-start<6
    assert stats['calls']==1 and stats['model']=='test-model' and stats['version']=='completed-before-cleanup'
    assert stats['attempts']==[{'model':'test-model','outcome':'provider_timeout'}]


def test_no_key_means_no_fabricated_call(monkeypatch):
    monkeypatch.delenv('POD_ABSENT_KEY',raising=False)
    stats={'calls':0,'attempts':[]}
    _,code=bounded_provider.invoke({'model':'test-model','api_key_env':'POD_ABSENT_KEY','deadline_s':1},'facts',{},[],stats)
    assert code=='provider_unconfigured' and stats=={'calls':0,'attempts':[]}
