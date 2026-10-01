"""Business services. Routes stay thin; business rules live here."""


class ValidationError(Exception):
    """Invalid user input. ``errors`` maps field names to messages."""

    def __init__(self, errors: dict[str, str]):
        super().__init__("; ".join(f"{k}: {v}" for k, v in errors.items()))
        self.errors = errors


class NotFound(Exception):
    pass
