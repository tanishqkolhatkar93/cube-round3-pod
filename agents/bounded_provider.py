"""One killable Gemini request per unit. Parent-owned accounting survives errors."""
import base64
import multiprocessing
import os
import time
from urllib.parse import quote
from agents.prep.common import strict_json


def worker(connection, selection, key, prompt, payload, images):
    import httpx
    client, result = None, {'error': 'provider_unavailable'}
    try:
        parts = [{'text': __import__('json').dumps(payload, allow_nan=False)}]
        parts += [{'inline_data': {'mime_type': i['media_type'], 'data': base64.b64encode(i['bytes']).decode()}}
                  for i in images]
        client = httpx.Client(timeout=selection['deadline_s'], follow_redirects=False)
        connection.send({'event': 'attempt', 'model': selection['model']})
        response = client.post('https://generativelanguage.googleapis.com/v1beta/models/' +
            quote(selection['model'], safe='') + ':generateContent', headers={'X-goog-api-key': key},
            json={'systemInstruction': {'parts': [{'text': prompt}]},
                  'contents': [{'role': 'user', 'parts': parts}],
                  'generationConfig': {'temperature': 0, 'maxOutputTokens': 8192, 'responseMimeType': 'application/json'}})
        response.raise_for_status()
        body = response.json()
        version = body.get('modelVersion', 'unknown')
        if not isinstance(version, str) or not version or len(version) > 200:
            raise ValueError()
        connection.send({'event': 'accounting', 'version': version})
        candidates = body.get('candidates', [])
        if len(candidates) != 1 or candidates[0].get('finishReason') != 'STOP' or body.get('promptFeedback', {}).get('blockReason'):
            raise ValueError()
        raw = ''.join(p.get('text', '') for p in candidates[0].get('content', {}).get('parts', []))
        if not raw or len(raw) > 100_000:
            raise ValueError()
        result = {'data': strict_json(raw)}
    except httpx.TimeoutException:
        result = {'error': 'provider_timeout'}
    except (ValueError, TypeError, KeyError):
        result = {'error': 'invalid_provider_response'}
    except Exception:
        result = {'error': 'provider_unavailable'}
    finally:
        if client is not None:
            try:
                client.close()
            except Exception:
                result.setdefault('error', 'provider_cleanup_failure')
        try:
            connection.send({'event': 'result', **result})
        finally:
            connection.close()


def invoke(selection, prompt, payload, images, stats):
    if not selection or not os.environ.get(selection['api_key_env']):
        return None, 'provider_unconfigured'
    context = multiprocessing.get_context('spawn')
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(target=worker, args=(sender, selection, os.environ[selection['api_key_env']],
                                                  prompt, payload, images), daemon=True)
    deadline = time.monotonic() + selection['deadline_s']
    code, data = 'provider_timeout', None
    try:
        process.start(); sender.close()
        while time.monotonic() < deadline:
            if not receiver.poll(max(0, deadline-time.monotonic())):
                break
            event = receiver.recv()
            if event['event'] == 'attempt':
                stats['calls'] = stats.get('calls', 0) + 1
                stats['model'] = event['model']
                stats.setdefault('attempts', []).append({'model': event['model'], 'outcome': 'started'})
            elif event['event'] == 'accounting':
                stats['version'] = event['version']
            elif event['event'] == 'result':
                code, data = event.get('error'), event.get('data')
                break
    except Exception:
        code = 'provider_unavailable'
    finally:
        receiver.close(); sender.close()
        if process.pid is not None:
            process.join(0.05)
            if process.is_alive():
                process.terminate(); process.join(0.5)
            if process.is_alive():
                process.kill(); process.join(0.5)
        if stats.get('attempts'):
            stats['attempts'][-1]['outcome'] = code or 'success'
    return data, code
