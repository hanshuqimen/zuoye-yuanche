class DomainError(Exception):
    """An expected, public failure; contains no private credentials or tracebacks."""

    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


class NotImplementedFeature(DomainError):
    def __init__(self, feature: str):
        super().__init__("NOT_IMPLEMENTED", f"尚未验证或实现：{feature}", 501)

