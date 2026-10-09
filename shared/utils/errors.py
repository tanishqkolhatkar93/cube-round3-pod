"""Errors an agent raises when supplied input is invalid."""


class AgentInputError(ValueError):
    """Invalid request data, distinct from a tenant authorization failure."""
