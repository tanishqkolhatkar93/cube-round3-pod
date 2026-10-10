"""Authenticated uploads bind only to existing, independently trusted captures."""
import hashlib
import io
import json
import os
import warnings
from pathlib import Path

from fastapi import HTTPException
from PIL import Image

from .store import identifier

MAX_BYTES = 10_000_000
TYPES = {'image/jpeg': 'JPEG', 'image/png': 'PNG', 'image/webp': 'WEBP'}
IMAGE_STAGES = ('receiving', 'prep', 'pack', 'returns')


def registered_inputs(org, unit, stage):
    request = {'subject': {'org_id': org, 'subject_id': unit},
               'workflow_id': f'WF-{org}-{unit}', 'inputs': []}
    try:
        if stage == 'receiving':
            from agents.receiving import app as receiving
            receiving._lookup(unit, org)
            registry = Path(os.environ.get('RECEIVING_CAPTURE_REGISTRY', Path(receiving.__file__).parent / 'fixtures/captures.json'))
            captures = json.loads(registry.read_text(encoding='utf-8'))['captures']
            request['inputs'] = [{'ref': c['ref'], 'kind': 'image', 'sha256': c['sha256']}
                                 for c in captures if (c['org_id'], c['subject_id']) == (org, unit)]
            found, issues, _ = receiving._resolve_inputs(request, unit)
            if issues or not found:
                raise ValueError()
            return [item for item, raw in found]
        if stage in ('prep', 'returns'):
            import importlib
            adapter = importlib.import_module(f'agents.{stage}.app').configured_adapter()
            result = adapter.resolver.resolve(request)
            if getattr(result, 'failure', None):
                raise ValueError()
            return result.inputs
        if stage in ('pack', 'recovery'):
            from agents.secure_runtime import configuration
            from agents.prep.input_resolver import registered_bytes
            config, root, _ = configuration(stage)
            matches = [b for b in config['bindings'] if
                       (b['org_id'], b['subject_id'], b['workflow_id']) == (org, unit, request['workflow_id'])]
            if len(matches) != 1:
                raise ValueError()
            inputs = []
            for item in matches[0]['files']:
                registered_bytes(root, {k: item[k] for k in ('ref', 'path', 'sha256')}, MAX_BYTES if stage == 'pack' else 1_000_000)
                inputs.append({k: item[k] for k in ('ref', 'kind', 'sha256')})
            return inputs
        raise HTTPException(422, 'Recovery requires registered reports and upstream evidence; direct recovery photos are unsupported.')
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(422, f'{stage.title()} needs valid tenant-owned unit/capture registration and available source files. Ask the registration operator to provision these first.') from None


def validate_image(raw, mime):
    if mime not in TYPES or not raw or len(raw) > MAX_BYTES:
        raise HTTPException(422, 'Use JPEG, PNG or WebP images, at most 10 MB each.')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as picture:
                if picture.format != TYPES[mime] or picture.width * picture.height > 25_000_000:
                    raise ValueError()
                picture.verify()
    except Exception:
        raise HTTPException(422, 'Image is invalid, mismatched, or exceeds 25 megapixels.') from None


def resolve_image(org, unit, sha, capture_ref=None):
    """Resolve membership, not image semantics. Never call inference or create registrations.

    Scan every supported image contract, independently of routing facts. A route
    must not hide conflicting registrations or silently relabel an image.
    """
    if capture_ref is not None and (not isinstance(capture_ref, str) or not capture_ref.strip()
                                    or len(capture_ref) > 512):
        raise HTTPException(422, 'A valid existing capture reference is required.')
    matches = []
    for stage in IMAGE_STAGES:
        try:
            inputs = registered_inputs(org, unit, stage)
        except HTTPException:
            # Unconfigured or unavailable sources cannot authorize an association.
            continue
        for item in inputs:
            if (item.get('kind') == 'image' and item.get('sha256') == sha
                    and (capture_ref is None or item['ref'] == capture_ref)):
                matches.append((stage, item, inputs))
    if len(matches) == 1:
        return matches[0]
    ambiguous = len(matches) > 1
    raise HTTPException(409 if ambiguous else 422, {
        'status': 'unresolved',
        'code': 'ambiguous_capture' if ambiguous else 'capture_unresolved',
        'required_information': 'capture_ref' if ambiguous else 'registration',
        'message': (
            'These image bytes match multiple trusted captures. Enter the existing capture reference '
            'from the capture record, or ask the registration operator to resolve duplicate bindings, then retry.'
            if ambiguous else
            'No verified capture matches this image for the signed-in tenant and registered subject. '
            'Check the subject ID and any capture reference. The registration operator must provision '
            'the trusted capture, lineage and source files before you retry. No workflow was started for this image.'
        ),
    })


def save_upload(store, org, unit, raw, mime, capture_ref=None):
    try:
        identifier(unit)
        if len(unit) > 160:
            raise ValueError()
    except ValueError:
        raise HTTPException(422, 'A valid registered unit or order subject ID is required.') from None
    validate_image(raw, mime)
    sha = hashlib.sha256(raw).hexdigest()
    stage, matched, _ = resolve_image(org, unit, sha, capture_ref)
    receipt = {'org_id': org, 'unit_id': unit, 'stage': stage, 'input': matched}
    if capture_ref is not None:
        receipt['capture_ref'] = capture_ref
    key = hashlib.sha256(json.dumps(receipt, sort_keys=True).encode()).hexdigest()
    # Private, tenant-scoped store, never mounted as static content. Browser names are ignored.
    with store.transaction():
        folder = store.root / 'uploads'
        folder.mkdir(exist_ok=True)
        target = folder / (key + '.bin')
        if target.exists():
            if hashlib.sha256(target.read_bytes()).hexdigest() != sha:
                raise HTTPException(503, 'Stored upload failed integrity validation.')
        else:
            with target.open('xb') as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
        store._write('uploads', key, receipt)
    return {'receipt_id': key, 'unit_id': unit, 'stage': stage, 'ref': matched['ref'], 'status': 'evidence_accepted'}


def load_receipts(store, org, unit, ids):
    if not isinstance(ids, list) or not 1 <= len(ids) <= 24 or any(not isinstance(i, str) for i in ids) or len(set(ids)) != len(ids):
        raise HTTPException(422, 'Supply 1–24 unique upload receipts.')
    grouped = {}
    for key in ids:
        if not isinstance(key, str) or len(key) != 64 or any(c not in '0123456789abcdef' for c in key):
            raise HTTPException(422, 'Invalid upload receipt.')
        receipt = store._read('uploads', key)
        if not receipt or (receipt['org_id'], receipt['unit_id']) != (org, unit):
            raise HTTPException(422, 'Upload receipt is unavailable for this tenant and subject.')
        try:
            raw = (store.root / 'uploads' / (key + '.bin')).read_bytes()
        except OSError:
            raise HTTPException(503, 'Uploaded evidence is unavailable.') from None
        if hashlib.sha256(raw).hexdigest() != receipt['input']['sha256']:
            raise HTTPException(503, 'Uploaded evidence failed integrity validation.')
        stage, matched, current = resolve_image(org, unit, receipt['input']['sha256'], receipt.get('capture_ref'))
        if stage != receipt['stage'] or matched != receipt['input']:
            raise HTTPException(409, 'Capture registration changed; upload again.')
        grouped[stage] = current
    return grouped
