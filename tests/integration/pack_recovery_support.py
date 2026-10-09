"""Explicit offline scenarios, never imported by production.

The organizer fee lines supply synthetic report INPUTS, not Recovery judgments.
Pack observations are invented matching facts, not model accuracy benchmarks.
Real registration, byte/hash validation, rules, evidence and ledgers execute.
"""
import copy
import hashlib
import io
import json
from pathlib import Path

import pytest
from PIL import Image
from agents.pack import adapter as pack
from orchestration import orchestrator
from shared.utils import sample_data


class Scenarios:
    def __init__(self, root, monkeypatch, cases):
        self.root, self.monkeypatch = root, monkeypatch
        root.mkdir()
        self.configs={s:{'version':1,'bindings':[]} for s in ('pack','recovery')}
        self.inputs={};self.observations={};self.calls=[]
        original=orchestrator.discover_inputs
        def discover(subject,stage):
            if stage in self.configs:
                return copy.deepcopy(self.inputs.get((subject,stage),[]))
            return original(subject,stage)
        monkeypatch.setattr(orchestrator,'discover_inputs',discover)
        for case in cases:
            unit,org=case['unit_id'],case['org_id']
            for stage in ('pack','recovery'):
                if stage=='pack' and case['route']!='mfn':continue
                binding={'org_id':org,'subject_id':unit,'workflow_id':f'WF-{org}-{unit}',
                         'captured_at':'2026-10-01T10:00:00Z','refs':{},'files':[],
                         'trusted_agents':{'receiving':['receiving-manager@1.0.0'],
                            'prep':['pod14-prep-manager@1'],'pack':['pack-manager@2'],'returns':['returns-manager@1']}}
                if stage=='pack':
                    ref=f'{unit}/pack/synthetic.png'
                    binding['refs']={'order_id':'SYNTHETIC-'+unit}
                    binding['order_lines']={'SYNTHETIC-'+unit:1}
                    stream=io.BytesIO();Image.new('RGB',(40,40),(140,120,160)).save(stream,'PNG');raw=stream.getvalue()
                    self.observations[ref]={'ref':ref,'usable':True,'complete':True,
                                           'items':[{'sku':'SYNTHETIC-'+unit,'quantity':1}]}
                else:
                    ref=f'{unit}/recovery/report.json'
                    lines=[{'line_id':r['line_id'],'charge_type':r['charge_type'],'amount_usd':r['amount_usd'],
                            'currency':'USD','unit_scope':'unit','refs':{}} for r in sample_data.fee_lines(unit,org)]
                    raw=json.dumps({'org_id':org,'subject_id':unit,'workflow_id':binding['workflow_id'],
                                    'complete':True,'line_count':len(lines),'lines':lines}).encode()
                path=root/ref;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
                item={'ref':ref,'path':ref,'sha256':hashlib.sha256(raw).hexdigest(),'kind':'image' if stage=='pack' else 'document'}
                binding['files']=[item];self.configs[stage]['bindings'].append(binding)
                self.inputs[(unit,stage)]=[{k:item[k] for k in ('ref','sha256','kind')}]
        for stage in self.configs:
            self.save(stage)
            monkeypatch.setenv(stage.upper()+'_CONFIG',str(root/(stage+'.json')))
        monkeypatch.setattr(pack,'invoke',self.invoke)
        self.fresh_state('initial')

    def save(self,stage):
        (self.root/(stage+'.json')).write_text(json.dumps(self.configs[stage]))

    def fresh_state(self,name):
        for stage in self.configs:
            self.monkeypatch.setenv(stage.upper()+'_STATE_DIR',str(self.root/'state'/name/stage))

    def authorize_override(self,unit,override):
        binding=next(b for b in self.configs['recovery']['bindings'] if b['subject_id']==unit)
        binding.setdefault('trusted_overrides',[]).append(copy.deepcopy(override));self.save('recovery')

    def invoke(self,config,prompt,payload,images,stats):
        self.calls.append([i['ref'] for i in images])
        for i in images:
            assert hashlib.sha256(i['bytes']).hexdigest()==i['sha256']
        stats.update(provider='test',calls=1,model='offline-fixture',version='explicit-synthetic-v1',
                     attempts=[{'model':'offline-fixture','outcome':'success'}])
        return {'images':[copy.deepcopy(self.observations[i['ref']]) for i in images]},None


@pytest.fixture
def pack_recovery_synthetic(tmp_path,monkeypatch,cases):
    return Scenarios(tmp_path/'pack-recovery-synthetic',monkeypatch,cases)
