class AdasLogError(Exception):
    """Base error for the analyzer."""


class LogLoadError(AdasLogError):
    """The log file could not be read or decoded."""


class RuleLoadError(AdasLogError):
    """A rule pack is malformed."""


class LLMProviderError(AdasLogError):
    """An LLM provider failed (network, auth, malformed output)."""
