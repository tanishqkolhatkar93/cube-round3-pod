"""Registered complete fee reports and validated evidence; one batched inference."""
from decimal import Decimal, InvalidOperation
import math

from agents.prep.common import fields, strict_json, text


def money(value):
    if type(value) not in (int, float, str):
        raise ValueError()
    amount = Decimal(str(value))
    if not amount.is_finite() or not 0 <= amount <= 1_000_000 or amount != amount.quantize(Decimal('.01')):
        raise ValueError()
    return amount


def reports(documents, binding):
    charges, ids = [], set()
    for document in documents:
        report = strict_json(document['bytes'])
        fields(report, ('org_id','subject_id','workflow_id','complete','line_count','lines'))
        if any(report[k]!=binding[k] for k in ('org_id','subject_id','workflow_id')):
            raise ValueError('report_scope_mismatch')
        if report['complete'] is not True or type(report['line_count']) is not int or not isinstance(report['lines'],list):
            raise ValueError('incomplete_report')
        if len(report['lines'])!=report['line_count'] or len(report['lines'])>200:
            raise ValueError('report_count_mismatch')
        for line in report['lines']:
            fields(line, ('line_id','charge_type','amount_usd','currency','unit_scope','refs'))
            text(line['line_id']);text(line['charge_type'])
            if line['line_id'] in ids or line['currency']!='USD' or line['unit_scope'] not in ('unit','order','po_line'):
                raise ValueError()
            if not isinstance(line['refs'],dict) or any(binding.get('refs',{}).get(k)!=v for k,v in line['refs'].items()):
                raise ValueError('charge_reference_conflict')
            required_refs={'unit':(), 'order':('order_id',), 'po_line':('po_number','po_line')}[line['unit_scope']]
            if any(line['refs'].get(k) in (None,'') for k in required_refs):
                raise ValueError('charge_scope_reference_missing')
            ids.add(line['line_id']);money(line['amount_usd'])
            charges.append({**line, 'amount_usd':float(money(line['amount_usd'])), 'source_ref':document['ref']})
    return charges


def eligible(line, evidence):
    return [r for r in evidence if r['status']=='completed' and r['subject']['unit_scope']==line['unit_scope']
            and all(r['subject'].get('refs',{}).get(k)==v for k,v in line['refs'].items())]


def measurements_valid(record):
    m=record.get('payload',{}).get('measurements')
    if not isinstance(m,dict):return False
    def valid(k):
        return type(m.get(k)) in (int,float) and math.isfinite(m[k]) and 0<m[k]<=1_000_000
    if not valid('weight_g'):return False
    axes=('length','width','height')
    units=[unit for unit in ('cm','mm') if any(axis+'_'+unit in m for axis in axes)]
    if not units or any(not all(valid(axis+'_'+unit) for axis in axes) for unit in units):return False
    if len(units)==2 and any(not math.isclose(m[axis+'_mm'],10*m[axis+'_cm'],rel_tol=1e-9) for axis in axes):return False
    return True
