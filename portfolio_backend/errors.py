class PortfolioError(Exception):
    """Domain failure carrying a public error code, message, and HTTP status."""

    def __init__(self, code: str, message: str, status_code: int = 422) -> None:
        """Initialize an error that the API can expose without inspecting internals.

        Args:
            code: Stable machine-readable identifier for the failure.
            message: Human-readable explanation safe to return to callers.
            status_code: HTTP response status; defaults to 422 for invalid input.
        """
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
