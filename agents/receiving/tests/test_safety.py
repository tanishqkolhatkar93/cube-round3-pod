"""Real Receiving boundaries with offline model observations, not provider calls."""
import copy
import hashlib
import importlib
import io
import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PIL import Image
from fastapi.testclient import TestClient
from pydantic import ValidationError

from agents.receiving import app as a
from agents.receiving.safety import Rejected, Ledger, digest
from agents.receiving.core import engine
from agents.receiving.core.models import ImageObservation, ObsProvenance, POLineItem, CheckContext
from agents.receiving.core.config import CFG
from agents.receiving.core.failures import Failure
from agents.receiving.core.extraction import service
from agents.receiving.core.extraction.gemini import GeminiProvider
from agents.receiving.core.checks import sku, colour, variant
from shared.utils.hashing import verify
from shared.utils.schema import errors
from orchestration.clients import InProcClient
from orchestration.orchestrator import run_workflow, load_flow
from orchestration.store import MemoryStore

def request(inputs=None, rid="audit", org="org_demo_alpha", unit="UNIT-9001"):
    return {"schema_version":"1.0","request_id":rid,"workflow_id":f"WF-{org}-{unit}",
            "stage":"receiving","subject":{"org_id":org,"subject_id":unit,"route":"mfn"},
            "inputs":inputs or [],"previous_evidence":[],"context":{}}

def observations(n=1):
    return [ObsProvenance(image_id=f"img_{i+1}",sha256="a"*64,
        observation=ImageObservation(visible_sku_text="SKU-BOTTLE-750",
            visible_unit_count=24,count_confidence=.95,full_contents_visible=True,
            cartons_visible=2,label_colour_text="black",label_variant_text="750 ml",
            visible_components=["bottle","lid"],contents_open_for_inspection=True),
        quality={"verdict":"ACCEPTABLE"}) for i in range(n)]

def stats():
    return {"calls":1,"cached":0,"rejected":0,"model_ids":["offline-model"],"attempts":[{"model":"offline-model","outcome":"success"}]}

def valid(out):
    assert not errors("agent-output",out)
    assert verify(out["evidence"])

@pytest.fixture
def success(monkeypatch):
    fn=Mock(return_value=(observations(),stats(),[]))
    monkeypatch.setattr(a,"run_engine",fn)
    return fn

def test_authorized_success_schema_hash(register,success):
    out=a.handle(request([register()]))
    assert out["verdict"]=="PASS"
    valid(out)
    assert out["evidence"]["inputs"][0]["sha256"]==hashlib.sha256(b"image").hexdigest()

def test_foreign_subject_capture_rejected_before_inference(register,success):
    inp=register(ref="UNIT-9002/receiving/image.jpg",org="org_demo_bravo",subject="UNIT-9002")
    out=a.handle(request([inp]))
    assert out["error"]["code"]=="capture_rejected"
    success.assert_not_called()
    valid(out)

@pytest.mark.parametrize("ref",["../x.jpg","/tmp/x.jpg","C:/x.jpg","C:x.jpg",r"\\server\share\x.jpg","//server/x.jpg","x\\y.jpg","x/%2e%2e/y","x/./y","x//y","x\x00y"])
def test_unsafe_reference_no_bytes_read(ref,success,monkeypatch):
    spy=Mock(side_effect=AssertionError("capture bytes must not be read"))
    monkeypatch.setattr(Path,"read_bytes",spy)
    out=a.handle(request([{"ref":ref,"kind":"image"}]))
    assert out["error"]["code"]=="capture_rejected"
    spy.assert_not_called();success.assert_not_called()

def test_symlink_rejected(register,success,monkeypatch):
    inp=register()
    original=Path.is_symlink
    monkeypatch.setattr(Path,"is_symlink",lambda p: True if p.name=="image.jpg" else original(p))
    out=a.handle(request([inp]))
    assert out["error"]["code"]=="capture_rejected";success.assert_not_called()

@pytest.mark.parametrize("change",["bytes","request_hash"])
def test_digest_mismatch(register,success,change):
    inp=register()
    if change=="bytes":(a.DATA_INPUT/inp["ref"]).write_bytes(b"changed")
    else:inp["sha256"]="0"*64
    out=a.handle(request([inp]))
    assert out["error"]["code"]=="capture_rejected";success.assert_not_called()

@pytest.mark.parametrize("case",["missing","unauthorized","omitted","quality","provider"])
def test_partial_capture_set_never_passes(register,success,case):
    one=register()
    two=register("UNIT-9001/receiving/second.jpg",raw=b"second")
    inputs=[one,two]
    if case=="missing":(a.DATA_INPUT/two["ref"]).unlink()
    if case=="unauthorized":inputs.append({"ref":"OTHER/file.jpg","kind":"image"})
    if case=="omitted":inputs=[one]
    if case=="quality":
        prov=observations(2);prov[1].quality={"verdict":"REJECTED"};success.return_value=(prov,stats(),[])
    if case=="provider":success.return_value=(observations(),stats(),[{"image_id":"img_2","code":"agent_timeout"}])
    out=a.handle(request(inputs))
    assert out["status"]!="completed" and out["verdict"]=="UNCERTAIN" and out["error"]
    if case in ("missing","unauthorized","omitted"):success.assert_not_called()
    valid(out)

def test_units_per_carton_failure_reaches_output(register,success):
    one=register();two=register("UNIT-9001/receiving/second.jpg",raw=b"second")
    prov=observations(2);prov[0].observation.cartons_visible=1
    success.return_value=(prov,stats(),[])
    out=a.handle(request([one,two]))
    assert out["verdict"]=="FAIL"
    assert next(c for c in out["evidence"]["checks"] if c["check_key"]=="units_per_carton")["verdict"]=="FAIL"
    valid(out)

@pytest.mark.parametrize("raw",["wrong","1750ml"])
def test_wrong_variant(register,success,raw):
    prov=observations();prov[0].observation.label_variant_text=raw
    success.return_value=(prov,stats(),[])
    out=a.handle(request([register()]))
    assert out["verdict"]=="FAIL";valid(out)

@pytest.mark.parametrize("expected,observed,match",[("750ml","750 ML",True),("750 ml","750ml",True),("750ml","1750ml",False),("black","blackish",False)])
def test_normalization(expected,observed,match):
    assert variant._m(expected,observed)==match

@pytest.mark.parametrize("field",["visible_unit_count","printed_quantity","cartons_visible"])
def test_negative_counts_rejected(field):
    with pytest.raises(ValidationError):ImageObservation(**{field:-1})

@pytest.mark.parametrize("field,value", [("visible_sku_text","SKU-BOTTLE-750-OTHER"),("label_colour_text","blackish"),("label_variant_text","1750ml")])
def test_multiple_image_conflicts_are_uncertain(register,success,field,value):
    one=register();two=register("UNIT-9001/receiving/second.jpg",raw=b"second")
    prov=observations(2);setattr(prov[1].observation,field,value)
    success.return_value=(prov,stats(),[])
    out=a.handle(request([one,two]))
    assert out["verdict"]=="UNCERTAIN";valid(out)

@pytest.mark.parametrize("observed",["SKU-BOTTLE","SKU-BOTTLE-750-OTHER"])
def test_sku_substrings_fail(observed):
    p=observations()[0];p.observation.visible_sku_text=observed
    c=sku.run(CheckContext(po=POLineItem(sku="SKU-BOTTLE-750",qty_ordered=24),observations=[p],model_version="offline"))
    assert c.verdict=="FAIL"

def test_replay_restart_concurrency(register,success):
    req=request([register()])
    with ThreadPoolExecutor(max_workers=5) as pool:out=list(pool.map(lambda _:a.handle(req),range(10)))
    assert all(o==out[0] for o in out);assert success.call_count==1
    # A fresh process replays persisted state without an injected provider.
    import subprocess,sys
    env={**os.environ,"INPUT_DIR":str(a.DATA_INPUT),"PYTHONDONTWRITEBYTECODE":"1"}
    result=subprocess.run([sys.executable,"-B","-c",
        "import json,sys; from agents.receiving.app import handle; print(json.dumps(handle(json.load(sys.stdin))))"],
        input=json.dumps(req),capture_output=True,text=True,env=env,check=True)
    assert json.loads(result.stdout)==out[0]
    valid(out[0])

@pytest.mark.parametrize("change",["context","bytes","binding"])
def test_changed_content_conflict(register,success,isolated_receiving,change):
    inp=register();req=request([inp]);first=a.handle(req)
    if change=="context":req["context"]["changed"]=True
    elif change=="bytes":(a.DATA_INPUT/inp["ref"]).write_bytes(b"changed")
    else:
        p=isolated_receiving[1];d=json.loads(p.read_text());d["captures"][0]["sha256"]="0"*64;p.write_text(json.dumps(d))
    with pytest.raises(Rejected,match="request_content_conflict"):a.handle(req)
    valid(first)

def test_scope_identity():
    x=request()
    assert len({a._record_id(x),a._record_id(request(org="org_demo_bravo")),a._record_id(request(unit="UNIT-9002"))})==3

@pytest.mark.parametrize("corrupt",["foreign_org","foreign_subject","bad_hash"])
def test_upstream_rejected(corrupt,success):
    from shared.utils.hashing import seal
    prior=a.handle(request(rid="prior"))["evidence"]
    if corrupt=="foreign_org":prior["subject"]["org_id"]="foreign"
    elif corrupt=="foreign_subject":prior["subject"]["subject_id"]="OTHER"
    prior=seal(prior)
    if corrupt=="bad_hash":prior["content_hash"]="0"*64
    req=request();req["previous_evidence"]=[prior]
    with pytest.raises(Rejected,match="unexpected_upstream_evidence"):a.handle(req)
    success.assert_not_called()

def dark():
    b=io.BytesIO();Image.new("RGB",(640,480),(12,12,12)).save(b,"JPEG");return b.getvalue()

@pytest.mark.parametrize("case",["missing","invalid","rejected"])
def test_deterministic_paths_without_credentials(register,monkeypatch,case):
    constructor=Mock(side_effect=AssertionError("must not create provider"))
    monkeypatch.setattr("agents.receiving.core.extraction.gemini.GeminiProvider",constructor)
    inp=[] if case=="missing" else [register(raw=b"invalid" if case=="invalid" else dark())]
    out=a.handle(request(inp))
    assert out["verdict"]=="UNCERTAIN";valid(out);constructor.assert_not_called()

class FakeProvider:
    name="gemini"
    calls=0
    def analyze(self,req,*,stats,deadline):
        type(self).calls+=1;stats["calls"]+=1;stats["attempts"].append({"model":"fallback-model","outcome":"success"})
        return SimpleNamespace(parsed=ImageObservation(),model_id="fallback-model",tokens=2,latency_ms=1)
    def close(self):pass

def prepare_service(monkeypatch):
    monkeypatch.setattr(service,"assess_quality",lambda b:{"verdict":"ACCEPTABLE"})
    monkeypatch.setattr(service,"decode_barcodes",lambda b:[])
    monkeypatch.setattr("agents.receiving.core.extraction.gemini.GeminiProvider",FakeProvider)
    FakeProvider.calls=0

def test_cache_atomic_concurrent_misses_and_model_identity(monkeypatch):
    prepare_service(monkeypatch)
    def run(_):return engine.run_engine([("image.jpg",dark())])
    with ThreadPoolExecutor(max_workers=4) as pool:results=list(pool.map(run,range(6)))
    assert FakeProvider.calls==1
    assert sum(s["calls"] for _,s,_ in results)==1
    assert sum(s["cached"] for _,s,_ in results)==5
    for p,s,e in results:
        assert not e and a._model_info(s)["version"]=="fallback-model"

@pytest.mark.parametrize("code",["agent_timeout","model_invalid_response","provider_configuration_required","model_error"])
def test_structured_provider_failure(register,monkeypatch,code):
    prepare_service(monkeypatch)
    def fail(self,*args,**kw):raise Failure(code)
    monkeypatch.setattr(FakeProvider,"analyze",fail)
    out=a.handle(request([register(raw=dark())]))
    assert out["error"]["code"]==code and out["verdict"]=="UNCERTAIN"
    valid(out)

def test_http_validation_and_conflict(register,success):
    client=TestClient(a.app)
    assert client.get("/health").json()["stage"]=="receiving"
    assert client.post("/run",json={}).status_code==422
    req=request([register()])
    assert client.post("/run",json=req).status_code==200
    req["context"]["changed"]=True
    assert client.post("/run",json=req).status_code==409

def test_current_test_orchestrator_partial_failure_not_clean(register,success,monkeypatch):
    import orchestration.orchestrator as orch
    inp=register();success.return_value=(observations(),stats(),[{"image_id":"img_2","code":"agent_timeout"}])
    monkeypatch.setattr(orch,"discover_inputs",lambda subject,stage:[inp])
    wf=run_workflow({"org_id":"org_demo_alpha","unit_id":"UNIT-9001"},
        {"flow_id":"audit","steps":[{"stage":"receiving"}]},MemoryStore(),
        {"receiving":InProcClient({"module":"agents.receiving.app"})})
    assert wf["status"]=="FAILED" and wf["final_outcome"]["outcome"]=="INCOMPLETE"

def test_provider_attempt_accounting_and_fallback_uses_real_sdk_types(monkeypatch):
    from google.genai import types
    import time
    from agents.receiving.core.extraction.base import VisionRequest
    provider=GeminiProvider.__new__(GeminiProvider)
    provider.types=types
    provider.models=["primary","fallback"]
    calls=[]
    def generate(**kwargs):
        calls.append(kwargs)
        assert kwargs["config"].http_options.timeout <= 20000
        assert kwargs["config"].http_options.retry_options.attempts == 1
        if len(calls)<3:
            return SimpleNamespace(text='{"visible_unit_count":-1}',usage_metadata=None)
        return SimpleNamespace(text=ImageObservation().model_dump_json(),usage_metadata=None)
    provider.client=SimpleNamespace(models=SimpleNamespace(generate_content=generate))
    s={"calls":0,"attempts":[]}
    response=provider.analyze(VisionRequest(image_bytes=b"fake",prompt_text="offline",
        prompt_version="v",schema_model=ImageObservation),stats=s,deadline=time.monotonic()+20)
    assert response.model_id=="fallback" and s["calls"]==3
    assert [x["outcome"] for x in s["attempts"]]==["model_invalid_response","model_invalid_response","success"]

def test_provider_timeout_is_bounded_and_sanitized(monkeypatch):
    from google.genai import types
    import time
    from agents.receiving.core.extraction.base import VisionRequest
    provider=GeminiProvider.__new__(GeminiProvider);provider.types=types;provider.models=["primary"]
    def fail(**kw):raise TimeoutError("SECRET raw provider diagnostic")
    provider.client=SimpleNamespace(models=SimpleNamespace(generate_content=fail))
    s={"calls":0,"attempts":[]}
    with pytest.raises(Failure,match="agent_timeout") as caught:
        provider.analyze(VisionRequest(image_bytes=b"fake",prompt_text="offline",
            prompt_version="v",schema_model=ImageObservation),stats=s,deadline=time.monotonic()+2)
    assert "SECRET" not in str(caught.value) and s["calls"]==1
    assert s["attempts"]==[{"model":"primary","outcome":"agent_timeout"}]

def test_provider_initialization_failure_sanitized(register,monkeypatch):
    from google import genai
    prepare_service(monkeypatch)
    monkeypatch.setattr("agents.receiving.core.extraction.gemini.GeminiProvider",GeminiProvider)
    monkeypatch.setattr(CFG,"gemini_api_key","offline-placeholder")
    def fail(*args,**kwargs):raise ValueError("SECRET")
    monkeypatch.setattr(genai,"Client",fail)
    out=a.handle(request([register(raw=dark())]))
    assert out["error"]["code"]=="provider_initialization_failed"
    assert "SECRET" not in json.dumps(out)
    valid(out)

def test_missing_credentials_after_valid_gate_is_structured(register,monkeypatch):
    prepare_service(monkeypatch)
    monkeypatch.setattr("agents.receiving.core.extraction.gemini.GeminiProvider",GeminiProvider)
    out=a.handle(request([register(raw=dark())]))
    assert out["error"]["code"]=="provider_configuration_required"
    valid(out)

def test_multiple_failures_and_uncertainty_cannot_export_pass(register,success):
    p=observations()[0]
    p.observation.label_variant_text="1750ml"
    p.observation.label_colour_text="red"
    p.observation.visible_unit_count=None
    success.return_value=([p],stats(),[])
    out=a.handle(request([register()]))
    assert out["verdict"]=="FAIL"
    checks=out["evidence"]["checks"]
    assert any(c["verdict"]=="FAIL" for c in checks) and any(c["verdict"]=="UNCERTAIN" for c in checks)
    valid(out)

def test_internal_exception_is_structured(register,success):
    success.side_effect=RuntimeError("SECRET")
    out=a.handle(request([register()]))
    assert out["error"]["code"]=="model_error" and "SECRET" not in json.dumps(out)
    valid(out)

def test_crashed_transaction_rolls_back(isolated_receiving):
    import subprocess,sys
    path=Path(os.environ["RECEIVING_STATE_DIR"])
    ledger=Ledger(path)
    # An interrupted SQLite write transaction must not publish a reservation/result.
    child="import sqlite3,sys,os; db=sqlite3.connect(sys.argv[1]); db.execute('CREATE TABLE IF NOT EXISTS requests (identity TEXT PRIMARY KEY,fingerprint TEXT NOT NULL,output TEXT NOT NULL)'); db.execute('BEGIN IMMEDIATE'); db.execute(\"INSERT INTO requests VALUES ('dead','fp','{}')\"); os._exit(7)"
    run=subprocess.run([sys.executable,"-B","-c",child,str(ledger.db)],capture_output=True)
    assert run.returncode==7
    out=a.handle(request())
    assert out==a.handle(request())
    valid(out)

def test_specialist_flow_real_stage_order_with_receiving_boundary(register,monkeypatch):
    # Use a real sample MFN returned case so the existing downstream adapters run.
    from tests.conftest import ROOT
    import orchestration.orchestrator as orch
    from shared.utils import sample_data
    cases=json.loads((ROOT/"data/sample/cases.json").read_text())
    case=next(c for c in cases if c["route"]=="mfn" and c["returned"])
    inp=register(ref=case["unit_id"]+"/receiving/image.jpg",raw=dark(),
                 org=case["org_id"],subject=case["unit_id"])
    monkeypatch.setattr(orch,"discover_inputs",lambda subject,stage:[inp] if stage=="receiving" else [])
    # Returns config is supplied by the existing root tests/conftest autouse fixture.
    # Explicitly prepare that declared synthetic fixture for this separately located suite.
    import tempfile,shutil
    folder=Path(os.environ["RECEIVING_STATE_DIR"]).parent/"returns-fixture";folder.mkdir()
    shutil.copyfile(ROOT/"data/sample/returns_sample.csv",folder/"returns_sample.csv")
    config={"mode":"synthetic","csv":"returns_sample.csv","tenants":[
        {"organization_id":"org_demo_alpha","client_id":None},{"organization_id":"org_demo_bravo","client_id":None}]}
    (folder/"config.json").write_text(json.dumps(config))
    monkeypatch.setenv("RETURNS_CONFIG",str(folder/"config.json"))
    monkeypatch.setenv("RETURNS_STATE_DIR",str(folder/"state"))
    monkeypatch.setenv("ORCH_MODE","inproc")
    store=MemoryStore();wf=run_workflow(case,load_flow(ROOT/"orchestration/flow.specialist.json"),store)
    assert [s["stage"] for s in wf["stage_results"]]==["receiving","pack","returns","recovery"]
    assert wf["final_outcome"]["outcome"]!="CLEAN"
    receiving=store.get_evidence(wf["stage_results"][0]["record_id"])
    assert receiving["agent_id"]=="receiving-manager@1.0.0" and receiving["decision"]["verdict"]=="UNCERTAIN"
    assert not errors("workflow-state",wf)
    for rid in wf["evidence_references"]:
        assert verify(store.get_evidence(rid))


def test_same_request_id_separated_across_valid_tenants_and_subjects():
    x=a.handle(request())
    y=a.handle(request(org="org_demo_bravo",unit="UNIT-9002"))
    assert x["evidence"]["record_id"] != y["evidence"]["record_id"]
    assert x==a.handle(request()) and y==a.handle(request(org="org_demo_bravo",unit="UNIT-9002"))
    valid(x);valid(y)


def test_concurrent_process_replay_is_identical():
    import subprocess,sys
    env={**os.environ,"INPUT_DIR":str(a.DATA_INPUT),"PYTHONDONTWRITEBYTECODE":"1"}
    script="import json,sys; from agents.receiving.app import handle; print(json.dumps(handle(json.load(sys.stdin))))"
    processes=[subprocess.Popen([sys.executable,"-B","-c",script],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,env=env) for _ in range(2)]
    for p in processes:
        p.stdin.write(json.dumps(request()));p.stdin.close();p.stdin=None
    results=[p.communicate(timeout=30) for p in processes]
    assert all(p.returncode==0 for p in processes),results
    assert json.loads(results[0][0])==json.loads(results[1][0])


def test_valid_upstream_and_wrong_stage_rejected_inproc(success):
    client=InProcClient({"module":"agents.receiving.app"})
    from orchestration.clients import AgentRejected
    req=request();req["stage"]="pack"
    with pytest.raises(AgentRejected):client.run(req,1)
    success.assert_not_called()
