from __future__ import annotations


class SentinelWardError(Exception):
    """Base class for normalized application errors."""


class ContractError(SentinelWardError):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


class ConfigurationError(SentinelWardError):
    pass


class DeliveryError(SentinelWardError):
    def __init__(self, code: str, detail: str, *, retryable: bool) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.retryable = retryable
