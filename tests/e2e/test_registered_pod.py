"""Positive FBA and MFN workflows through the actual entry points/transports.

No decision is mocked. Only observation transports are replaced with explicit
synthetic facts; all registrations, rules, hashes, ledgers and handoffs execute.
"""
import json
from pathlib import Path

import pytest
from agents.prep.tests.integration_support import prep_synthetic
from agents.receiving.tests.integration_support import receiving_observed
from tests.integration.pack_recovery_support import pack_recovery_synthetic
from tests.e2e.test_http import servers
from orchestration.orchestrator import run_workflow
from orchestration.store import MemoryStore
from shared.utils import sample_data
from shared.utils.hashing import verify
from shared.utils.schema import errors


@pytest.fixture(params=['fba','mfn'])
def cases(request):
    values=json.loads((Path(__file__).resolve().parents[2]/'data/sample/cases.json').read_text())
    def consistent(case):
        spec=sample_data.row('receiving',case['unit_id'],case['org_id'])
        try:
            return int(spec['qty_ordered'])==int(spec['cartons_ordered'])*int(spec['units_per_carton_ordered'])
        except (ValueError,TypeError):return False
    selected=next(c for c in values if c['route']==request.param and not c['returned']
                  and c['unit_id']!='UNIT-0012' and consistent(c))
    # Receiving's explicit fixture registers cases[0]. The remaining cases retain
    # its existing routing/example selections and both-organization configuration.
    return [selected,*[c for c in values if c!=selected]]


@pytest.mark.parametrize('transport',['inproc','http'])
def test_registered_route_completes_with_real_agents(cases,transport,servers,monkeypatch,
        receiving_observed,prep_synthetic,pack_recovery_synthetic):
    monkeypatch.setenv('ORCH_MODE',transport)
    for stage,url in servers.items():monkeypatch.setenv(stage.upper()+'_URL',url)
    store=MemoryStore();case=cases[0]
    # Explicit positive sources: a supported Prep fee for FBA, and a trusted
    # complete zero-charge report for MFN. Unknown-policy coverage stays separate.
    lines=[{'line_id':'positive-fee','charge_type':'inbound_defect_fee',
            'amount_usd':'4.25','currency':'USD','unit_scope':'unit','refs':{}}] if case['route']=='fba' else []
    pack_recovery_synthetic.set_fee_report(case['unit_id'],lines)
    workflow=run_workflow(case,store=store)
    assert workflow['status']=='COMPLETED', [(s['stage'],s.get('verdict'),s.get('needs_human')) for s in workflow['stage_results']]
    assert workflow['final_outcome']['provisional'] is False
    active=[s for s in workflow['stage_results'] if s['state']!='skipped']
    route_stage='prep' if case['route']=='fba' else 'pack'
    assert [s['stage'] for s in active]==['receiving',route_stage,'recovery']
    assert all(s['state']=='completed' and s['error'] is None for s in active)
    records=[store.get_evidence(s['record_id']) for s in active]
    assert records[0]['decision']['verdict']=='PASS'
    assert records[1]['decision']['verdict']=='PASS'
    assert all(verify(r) and not errors('evidence',r) for r in records)
    assert all('stub' not in r['agent_id'] and r['model']['name']!='csv-replay-stub' for r in records)
    assert records[1]['upstream_refs']==[records[0]['record_id']]
    assert set(records[2]['upstream_refs'])=={r['record_id'] for r in records[:2]}
    assert records[2]['inputs'] and records[2]['payload']['report_complete'] is True
    assert records[2]['payload']['claimable_usd']==(4.25 if case['route']=='fba' else 0)
    assert records[2]['decision']['outcome']==('claim_recommended' if case['route']=='fba' else 'no_claim')
    assert len(receiving_observed)==1
    assert (sum(prep_synthetic.calls.values()) if route_stage=='prep' else len(pack_recovery_synthetic.calls))==1
