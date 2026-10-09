"""Pack-specific validation and failure semantics around Tanishq's SDK engine.

Registration, ownership and the durable ledger have one shared implementation in
secure_runtime. Only validated facts cross this boundary into the Pack checks.
"""
import json
import httpx
from agents import bounded_provider
from agents.prep.common import fields, text
from shared.utils.hashing import seal
from shared.utils.records import pending_output as shared_pending_output, build_output, check
from . import vision

PROMPT = vision.PROMPT


def worker(connection, selection, key, prompt, payload, images):
    client = None
    result = {'error':'provider_unavailable'}
    try:
        client = vision.get_client(selection, key)
        response = vision.analyze_package_image(images, json.dumps(payload['order_lines']),
            client=client, selection=selection, report=connection.send)
        result = {'data':{'images':[v.model_dump() for v in response.images],
                  'assessment':{'verdict':response.verdict,'checks_performed':response.checks_performed.model_dump()}}}
    except httpx.TimeoutException:
        result = {'error':'provider_timeout'}
    except (ValueError, TypeError, KeyError):
        result = {'error':'invalid_provider_response'}
    except Exception:
        result = {'error':'provider_unavailable'}
    finally:
        if client is not None:
            try:client.close()
            except Exception:result.setdefault('error','provider_cleanup_failure')
        try:connection.send({'event':'result',**result})
        finally:connection.close()


def invoke(selection, prompt, payload, images, stats):
    return bounded_provider.invoke(selection, prompt, payload, images, stats, worker_target=worker)


def observations(response, images):
    fields(response, ('images',), ('assessment',))
    views = response['images']
    if not isinstance(views,list) or len(views)!=len(images):raise ValueError('missing_view')
    refs = {i['ref'] for i in images}
    seen = {}
    for view in views:
        fields(view, ('ref','usable','complete','items'))
        if view['ref'] not in refs or view['ref'] in seen:raise ValueError('invalid_ref')
        if type(view['usable']) is not bool or type(view['complete']) is not bool or not isinstance(view['items'],list):
            raise ValueError('invalid_view')
        counts = {}
        for item in view['items']:
            fields(item, ('sku','quantity')); text(item['sku'])
            if item['sku'] in counts or type(item['quantity']) is not int or not 1<=item['quantity']<=100_000:
                raise ValueError('invalid_count')
            counts[item['sku']] = item['quantity']
        seen[view['ref']] = counts
    if any(not v['usable'] or not v['complete'] for v in views):return None,'incomplete_observation'
    counts = list(seen.values())
    if not counts or any(v!=counts[0] for v in counts[1:]):return None,'contradictory_observations'
    assessment = response.get('assessment')
    if assessment is not None:
        fields(assessment, ('verdict','checks_performed'))
        flags = assessment['checks_performed']
        fields(flags, ('all_items_present','quantities_correct','no_extra_items'))
        if any(type(v) is not bool for v in flags.values()) or assessment['verdict'] not in ('SEAL','STOP_AND_FIX','UNCERTAIN'):
            raise ValueError('invalid_assessment')
        if assessment['verdict']=='UNCERTAIN':return None,'model_uncertain'
    return counts[0],None


def model_metadata(stats):
    return {'name':stats.get('model','none'), 'version':stats.get('version','unknown'),
            'provider':stats.get('provider','google') if stats['calls'] else None,
            'calls':stats['calls'], 'prompt_version':'tanishq-pack-v2'}


def payload(request, binding, stats, fingerprint):
    return {'request_id':request['request_id'],'request_fingerprint':fingerprint,
            'source_kind':'trusted_registration','order_lines':binding['order_lines'],
            'provider_attempts':stats['attempts'],'provider_usage':stats.get('usage',{}),
            'observations':None}


def pending_output(request, binding, inputs, rid, stats, fingerprint, code):
    result = shared_pending_output(request,code=code,message=code,agent_id='pack-manager@2')
    record = result['evidence']
    record.update(record_id=rid,captured_at=binding['captured_at'],client_id=binding.get('client_id'),
                  inputs=inputs,model=model_metadata(stats),payload=payload(request,binding,stats,fingerprint))
    record['subject'].update(unit_scope='order',refs=binding['refs'])
    record['checks'] = [check(k,'UNCERTAIN',None,observed='unavailable',detail=code,
        uncertain_reason=('model_error' if code.startswith('provider_') else
                          'conflicting_evidence' if code=='contradictory_observations' else 'insufficient_evidence'),
        evidence_refs=[i['ref'] for i in inputs])
        for k in ('items_present','quantities_correct','no_extra_items')]
    return build_output(seal(record),next_step='review')
