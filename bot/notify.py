"""Отправка служебных уведомлений, которые не должны ронять бота при ошибке."""
from __future__ import annotations

import logging

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import InlineKeyboardMarkup

from .config import Settings

log = logging.getLogger(__name__)


async def notify_vets(bot: Bot, settings: Settings, text: str) -> None:
    if not settings.vet_chat_id:
        return
    try:
        await bot.send_message(settings.vet_chat_id, text)
    except TelegramAPIError as e:
        log.warning("Не удалось отправить уведомление в чат ветеринаров: %s", e)


async def safe_send(bot: Bot, chat_id: int, text: str, reply_markup: InlineKeyboardMarkup | None = None) -> bool:
    """Отправка пользователю. False, если пользователь заблокировал бота или чат недоступен."""
    try:
        await bot.send_message(chat_id, text, reply_markup=reply_markup)
        return True
    except TelegramAPIError as e:
        log.info("Не удалось отправить сообщение %s: %s", chat_id, e)
        return False
