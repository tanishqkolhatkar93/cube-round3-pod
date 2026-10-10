"""Offline configuration diagnostics. Never infer source validity or call a model."""
import os


HTTP_CODES = {400: 'provider_request_rejected', 401: 'provider_authentication_failed',
              403: 'provider_authentication_failed', 404: 'provider_model_unavailable',
              429: 'provider_rate_limited', 503: 'provider_overloaded'}
PROVIDER_HTTP_ERRORS = frozenset({*HTTP_CODES.values(), 'provider_http_error'})


def provider_http_error(status):
    return HTTP_CODES.get(status, 'provider_http_error')


CONFIGURATION_CODES = frozenset({
    'prep_configuration_required', 'prep_configuration_invalid',
    'returns_configuration_required', 'returns_configuration_invalid',
    'configuration_required', 'invalid_configuration', 'invalid_registration',
    'invalid_provider_configuration', 'explicit_client_scope_required',
    'ambiguous_tenant_configuration', 'explicit_source_mode_required',
    'explicit_real_provider_required', 'unknown_returns_provider',
    'groq_invalid_key_selector', 'groq_key_missing', 'groq_invalid_configuration',
    'gemini_key_missing', 'gemini_invalid_configuration',
    'gemini_free_tier_confirmation_required', 'provider_timeout_exceeds_adapter_budget',
    'ollama_invalid_configuration', 'live_inspection_cannot_use_fixtures',
    'synthetic_mode_does_not_invoke_providers',
})


def configuration_code(exc, default):
    code = str(exc)
    return code if code in CONFIGURATION_CODES else default


def provider_readiness(selection, *, required=True):
    """Presence is not remote authentication, model availability or quota."""
    configured = bool(selection and os.environ.get(selection['api_key_env']))
    return {
        'provider': selection.get('kind', 'gemini') if selection else None,
        'provider_configured': configured,
        'provider_required': 'always' if required else 'eligible_policy_lines_only',
        'provider_status': 'not_verified' if configured else 'provider_unconfigured',
    }


def checks_not_run():
    return {'source_validation': 'per_request', 'remote_provider_validation': 'not_run'}
