"""Ephemeral diagnostics only. Never return provider values or unknown field names.

The canonical parser remains the authority; this module cannot accept/repair output.
"""
from dataclasses import replace
import json
from . import observations as canonical
from .domain import ValidationError, TenantMismatch

FIELDS = {
    '$': {'scope', 'identity', 'components', 'condition', 'limitations'},
    'identity': {'field', 'state', 'values', 'evidence_refs', 'limitations'},
    'components': {'component', 'presence', 'visibility', 'quantity', 'quantity_reliable', 'absence_basis', 'evidence_refs', 'limitations'},
    'condition': {'feature', 'state', 'description', 'evidence_refs', 'limitations'},
}
ENUMS = {'identity': {'field': canonical.IDENTITY_FIELDS, 'state': canonical.STATES},
         'components': {'presence': {'present', 'absent', 'unknown', 'conflicting'}, 'visibility': canonical.VISIBILITY},
         'condition': {'feature': canonical.CONDITION_FEATURES, 'state': canonical.STATES}}
# Only fixed messages from the canonical code may be exposed. No exception text fallback.
RULES = {message: field for message, field in (
    ('observed/conflicting identity needs explicit values', 'values'),
    ('unavailable identity cannot assert values', 'values'),
    ('uncertain identity needs limitations', 'limitations'),
    ('quantity_reliable must be boolean', 'quantity_reliable'),
    ('quantity must be nonnegative integer or null', 'quantity'),
    ('unreliable quantity must remain null', 'quantity'),
    ('quantity cannot be inferred from obscured/conflicting evidence', 'quantity'),
    ('present component needs visibility', 'visibility'),
    ('absence needs explicit full coverage basis and explanation', 'absence_basis'),
    ('absence basis only applies to an absence assertion', 'absence_basis'),
    ('uncertain component needs limitations', 'limitations'),
    ('visible finding needs a provider description', 'description'),
    ('unavailable condition cannot assert a finding', 'description'),
    ('negative/uncertain finding needs visible-scope limitations', 'limitations'),
    ('unknown, duplicated or unavailable evidence reference', 'evidence_refs'),
    ('substantive observation needs supplied evidence', 'evidence_refs'),
    ('conflicting observation needs multiple evidence items', 'evidence_refs'),
)}


def diagnostic(category, path, expected, value=None):
    types = {str:'string', int:'integer', float:'number', bool:'boolean', list:'array', dict:'object', type(None):'null'}
    return {'category': category, 'path': path, 'expected': expected,
            'actual_type': types.get(type(value), 'unsupported_type')}


def fields(value, expected, path):
    if type(value) is not dict:
        return diagnostic('type', path, 'object', value)
    if set(value) != expected:
        return {**diagnostic('fields', path, 'exact canonical fields', value),
                'missing_fields': sorted(expected - set(value)),
                'unexpected_field_count': len(set(value) - expected)}


def diagnose(capture, images, response):
    try:
        canonical.validate_response(response)
    except ValidationError:
        return diagnostic('response_metadata_or_limits', '$response', 'canonical ProviderResponse')
    try:
        payload = json.loads(response.text, object_pairs_hook=canonical._unique_object,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (ValueError, RecursionError):
        return diagnostic('json', '$', 'unique-key finite JSON object')
    result = fields(payload, FIELDS['$'], '$')
    if result: return result
    for section in ('identity', 'components', 'condition'):
        entries = payload[section]
        try: canonical.sequence(entries)
        except ValidationError: return diagnostic('type_or_limit', '$.' + section, 'array of at most 200 entries', entries)
        for index, item in enumerate(entries):
            path = f'$.{section}[{index}]'
            result = fields(item, FIELDS[section], path)
            if result: return result
            for field, values in ENUMS[section].items():
                if type(item[field]) is not str or item[field] not in values:
                    return diagnostic('enum', path + '.' + field, sorted(values), item[field])
            for field in ('values', 'evidence_refs', 'limitations', 'component', 'description'):
                if field not in item or field == 'description' and item[field] is None: continue
                try:
                    (canonical.strings if field in ('values','evidence_refs','limitations') else canonical.text)(item[field])
                except ValidationError:
                    return diagnostic('text_or_list_constraint', path + '.' + field,
                        'canonical text (1..8192 characters, valid Unicode, no edge whitespace/control characters); lists at most 200', item[field])
            # Isolate only for diagnosis; never return this probe as an observation.
            probe = {**payload, 'identity': [], 'components': [], 'condition': [], 'limitations': []}
            probe[section] = [item]
            try: canonical.parse_response(capture, images, replace(response, text=json.dumps(probe)))
            except TenantMismatch: return diagnostic('scope', '$.scope', 'exact registered capture scope')
            except ValidationError as exc:
                rule = str(exc)
                return diagnostic('canonical_rule', path + ('.' + RULES[rule] if rule in RULES else ''),
                                  rule if rule in RULES else 'canonical observation constraints')
    try: canonical.strings(payload['limitations'])
    except ValidationError: return diagnostic('text_or_list_constraint', '$.limitations', 'bounded canonical string list', payload['limitations'])
    return diagnostic('canonical_validation', '$', 'canonical response, evidence and scope constraints')
