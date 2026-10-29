class DomainError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class LeaseLost(DomainError):
    def __init__(self):
        super().__init__("LEASE_LOST", "Execution no longer owns a valid task lease")
