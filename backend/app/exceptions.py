from __future__ import annotations


class SSAError(Exception):
    pass


class EntityNotFoundError(SSAError):
    pass


class IngestionError(SSAError):
    pass


class LLMClientError(SSAError):
    pass


class RetrievalError(SSAError):
    pass


class ConfigurationError(SSAError):
    pass
