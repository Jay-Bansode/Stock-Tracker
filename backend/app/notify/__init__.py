from app.config import Settings
from app.notify.base import Sender
from app.notify.telegram import TelegramSender
from app.notify.whatsapp import WhatsAppSender


def build_senders(settings: Settings) -> dict[str, Sender]:
    senders: dict[str, Sender] = {}
    if settings.telegram_enabled:
        senders["TELEGRAM"] = TelegramSender(
            settings.telegram_bot_token, settings.telegram_chat_id,
            api_base=settings.telegram_api_base,
        )
    if settings.whatsapp_enabled:
        senders["WHATSAPP"] = WhatsAppSender(
            settings.whatsapp_token,
            settings.whatsapp_phone_number_id,
            settings.whatsapp_to,
            settings.whatsapp_template,
            settings.whatsapp_template_lang,
            settings.whatsapp_graph_version,
            api_base=settings.whatsapp_api_base,
        )
    return senders
