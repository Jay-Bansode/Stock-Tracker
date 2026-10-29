from typing import Protocol

from app.notify.formatter import AlertMessage


class SendError(Exception):
    def __init__(self, message: str, *, retryable: bool, retry_after: float | None = None):
        super().__init__(message)
        self.retryable = retryable
        self.retry_after = retry_after


class Sender(Protocol):
    channel: str

    async def send_alert(self, msg: AlertMessage) -> str: ...

    async def send_text(self, text: str) -> str: ...
