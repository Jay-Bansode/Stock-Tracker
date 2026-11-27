"""Two-way Telegram bot: commands (/price, /alerts, /add) and alert-message buttons.

Updates arrive either by webhook (free hosting, app/api/telegram.py) or by long polling
(Docker services mode, BotPoller run by the notifier process).
"""

import asyncio
import logging
from functools import lru_cache

from app.notify.base import SendError
from app.notify.telegram import TelegramApi

log = logging.getLogger(__name__)


@lru_cache
def bot_api(token: str, api_base: str) -> TelegramApi:
    return TelegramApi(token, api_base)


class BotPoller:
    """Long-polls getUpdates and hands each update to `handle`. Only one poller (or a webhook)
    can receive a bot's updates at a time."""

    def __init__(self, api: TelegramApi, handle, timeout: int = 25):
        self.api, self.handle, self.timeout = api, handle, timeout

    async def run(self) -> None:
        try:
            await self.api.delete_webhook()  # getUpdates is refused while a webhook is set
        except SendError as exc:
            log.warning("could not clear telegram webhook: %s", exc)
        offset: int | None = None
        log.info("telegram bot polling for messages")
        while True:
            try:
                updates = await self.api.get_updates(offset, self.timeout)
            except SendError as exc:
                log.warning("telegram getUpdates failed: %s", exc)
                await asyncio.sleep(exc.retry_after or 5)
                continue
            for upd in updates:
                offset = upd["update_id"] + 1
                await self.handle(upd)
