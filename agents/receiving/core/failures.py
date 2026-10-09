"""Safe diagnostics: no provider exception messages or credentials in evidence."""
class Failure(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)

def classify(exc):
    if isinstance(exc, Failure):
        return exc.code
    if isinstance(exc, TimeoutError) or "timeout" in type(exc).__name__.lower():
        return "agent_timeout"
    if type(exc).__name__ in ("ValidationError", "JSONDecodeError"):
        return "model_invalid_response"
    return "model_error"
