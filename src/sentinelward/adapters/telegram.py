from __future__ import annotations

import asyncio
import hashlib
import json
import os
import secrets
import time
from collections.abc import Awaitable, Callable
from datetime import timedelta
from pathlib import Path
from typing import Literal, TypeVar

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import RetryAfter, TelegramError

from sentinelward.alerts import (
    AlertStore,
    CallbackTarget,
    DeliveryRecord,
    ProviderMessage,
)
from sentinelward.contracts import AlertMessage, BedsideCheckMessage
from sentinelward.presentation import render_user_alert

CallbackConsumer = Callable[[str, str, str], Awaitable[object]]
T = TypeVar("T")


class TelegramIdentityMap:
    def __init__(self, mapping: dict[str, int]) -> None:
        self._by_staff = dict(mapping)
        self._by_chat = {str(chat_id): staff_id for staff_id, chat_id in mapping.items()}

    @classmethod
    def load(cls, path: Path) -> TelegramIdentityMap:
        if os.name != "nt" and path.stat().st_mode & 0o077:
            raise PermissionError("Telegram recipient map must use mode 0600")
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict) or not raw:
            raise ValueError("Telegram recipient map must be a non-empty JSON object")
        mapping: dict[str, int] = {}
        for staff_id, chat_id in raw.items():
            if not isinstance(staff_id, str) or not staff_id.startswith("staff:"):
                raise ValueError("Telegram recipient keys must be canonical staff IDs")
            if not isinstance(chat_id, int):
                raise ValueError("Telegram chat IDs must be integers")
            mapping[staff_id] = chat_id
        return cls(mapping)

    def chat_for(self, staff_id: str) -> int:
        try:
            return self._by_staff[staff_id]
        except KeyError as exc:
            raise LookupError(f"no Telegram destination for {staff_id}") from exc

    def staff_for(self, chat_id: str) -> str:
        try:
            return self._by_chat[chat_id]
        except KeyError as exc:
            raise PermissionError("Telegram sender is not mapped to a staff identity") from exc


class TelegramNotifier:
    def __init__(
        self,
        *,
        bot: Bot,
        identities: TelegramIdentityMap,
        store: AlertStore,
    ) -> None:
        self._bot = bot
        self._identities = identities
        self._store = store
        self._chat_locks: dict[int, asyncio.Lock] = {}
        self._last_send: dict[int, float] = {}

    async def send(
        self, alert: AlertMessage, staff_id: str, *, waveform_png: bytes | None
    ) -> ProviderMessage:
        chat_id = self._identities.chat_for(staff_id)
        keyboard = await self._keyboard(alert)
        user_text = render_user_alert(alert)
        async with self._chat_locks.setdefault(chat_id, asyncio.Lock()):
            delay = 1.0 - (time.monotonic() - self._last_send.get(chat_id, 0.0))
            if delay > 0:
                await asyncio.sleep(delay)
            if waveform_png:
                message = await self._with_retry_after(
                    lambda: self._bot.send_photo(
                        chat_id=chat_id,
                        photo=waveform_png,
                        caption=user_text,
                        reply_markup=keyboard,
                    )
                )
                has_media = True
            else:
                message = await self._with_retry_after(
                    lambda: self._bot.send_message(
                        chat_id=chat_id, text=user_text, reply_markup=keyboard
                    )
                )
                has_media = False
            self._last_send[chat_id] = time.monotonic()
        return ProviderMessage(
            message_id=str(message.message_id), chat_id=str(chat_id), has_media=has_media
        )

    async def edit_acknowledged(self, delivery: DeliveryRecord, *, by: str, at_ms: int) -> None:
        if delivery.provider_chat_id is None or delivery.provider_message_id is None:
            raise ValueError("delivered Telegram record has no provider message identity")
        text = f"✅ Acknowledged by {by} at {format_time(at_ms)}"
        chat_id = int(delivery.provider_chat_id)
        message_id = int(delivery.provider_message_id)
        if delivery.has_media:
            await self._with_retry_after(
                lambda: self._bot.edit_message_caption(
                    chat_id=chat_id, message_id=message_id, caption=text, reply_markup=None
                )
            )
        else:
            await self._with_retry_after(
                lambda: self._bot.edit_message_text(
                    chat_id=chat_id, message_id=message_id, text=text, reply_markup=None
                )
            )

    async def edit_active(self, delivery: DeliveryRecord, alert: AlertMessage) -> None:
        if delivery.provider_chat_id is None or delivery.provider_message_id is None:
            raise ValueError("delivered Telegram record has no provider message identity")
        keyboard = await self._keyboard(alert)
        user_text = render_user_alert(alert)
        chat_id = int(delivery.provider_chat_id)
        message_id = int(delivery.provider_message_id)
        if delivery.has_media:
            await self._with_retry_after(
                lambda: self._bot.edit_message_caption(
                    chat_id=chat_id,
                    message_id=message_id,
                    caption=user_text,
                    reply_markup=keyboard,
                )
            )
        else:
            await self._with_retry_after(
                lambda: self._bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=user_text,
                    reply_markup=keyboard,
                )
            )

    async def _keyboard(self, alert: AlertMessage) -> InlineKeyboardMarkup:
        actions: list[tuple[str, Literal["ack", "escalate", "patient_ok", "patient_not_ok"]]] = [
            ("On my way", "ack"),
            ("Escalate", "escalate"),
            ("Patient OK", "patient_ok"),
            ("Patient NOT OK", "patient_not_ok"),
        ]
        buttons: list[InlineKeyboardButton] = []
        for label, action in actions:
            token = secrets.token_urlsafe(16)
            await self._store.save_callback_target(
                CallbackTarget(
                    token=token,
                    alert_id=alert.alert_id,
                    bed_id=alert.bed_id,
                    alert_updated_ts=alert.ts,
                    action=action,
                )
            )
            buttons.append(InlineKeyboardButton(label, callback_data=token))
        return InlineKeyboardMarkup([buttons[:2], buttons[2:]])

    async def _with_retry_after(self, call: Callable[[], Awaitable[T]]) -> T:
        for attempt in range(3):
            try:
                return await call()
            except RetryAfter as exc:
                if attempt == 2:
                    raise
                retry_after = exc.retry_after
                seconds = (
                    retry_after.total_seconds()
                    if isinstance(retry_after, timedelta)
                    else float(retry_after)
                )
                await asyncio.sleep(seconds + 0.05)
        raise AssertionError("retry loop exited unexpectedly")


class TelegramCallbackRouter:
    def __init__(
        self,
        *,
        store: AlertStore,
        identities: TelegramIdentityMap,
        acknowledge: Callable[..., Awaitable[object]],
        escalate: Callable[..., Awaitable[object]],
        publish_bedside: Callable[[BedsideCheckMessage], Awaitable[None]],
    ) -> None:
        self._store = store
        self._identities = identities
        self._acknowledge = acknowledge
        self._escalate = escalate
        self._publish_bedside = publish_bedside

    async def __call__(self, token: str, callback_id: str, chat_id: str) -> object:
        del callback_id
        target = await self._store.get_callback_target(token)
        if target is None:
            raise LookupError("unknown or expired callback token")
        staff_id = self._identities.staff_for(chat_id)
        alert = await self._store.get_alert(target.alert_id)
        if alert is None or alert.bed_id != target.bed_id:
            raise LookupError("this alert no longer exists")
        if not alert.active or target.alert_updated_ts != alert.updated_ts:
            return alert
        timestamp = time.time_ns() // 1_000_000
        token_identity = hashlib.sha256(token.encode()).hexdigest()[:32]
        event_id = f"telegram:{token_identity}"
        if target.action == "ack":
            return await self._acknowledge(
                target.alert_id, by=staff_id, at_ms=timestamp, event_id=event_id
            )
        if target.action == "escalate":
            return await self._escalate(
                target.alert_id, by=staff_id, at_ms=timestamp, event_id=event_id
            )
        if alert.roster is not None and staff_id not in alert.roster.all_staff:
            raise PermissionError("Telegram sender is not on the current alert roster")
        if not await self._store.record_callback(event_id, target.alert_id):
            return alert
        await self._publish_bedside(
            BedsideCheckMessage(
                v=1,
                type="bedside_check",
                bed_id=target.bed_id,
                ts=timestamp,
                result=target.action,
                by=staff_id,
            )
        )
        return alert


class TelegramPoller:
    def __init__(self, bot: Bot, callback_consumer: CallbackConsumer) -> None:
        self._bot = bot
        self._callback_consumer = callback_consumer
        self._stopping = asyncio.Event()

    async def run(self) -> None:
        offset: int | None = None
        backoff = 1.0
        while not self._stopping.is_set():
            try:
                updates = await self._bot.get_updates(
                    offset=offset, timeout=30, allowed_updates=["callback_query"]
                )
            except TelegramError:
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30.0)
                continue
            backoff = 1.0
            for update in updates:
                offset = update.update_id + 1
                await self._handle(update)

    async def stop(self) -> None:
        self._stopping.set()

    async def _handle(self, update: Update) -> None:
        query = update.callback_query
        if query is None or query.data is None or query.message is None:
            return
        try:
            await self._callback_consumer(query.data, query.id, str(query.message.chat.id))
        except (LookupError, PermissionError, ValueError) as exc:
            await query.answer(str(exc)[:180], show_alert=True)
            return
        except Exception:
            await query.answer(
                "Unable to record this action. Use the central screen.", show_alert=True
            )
            return
        await query.answer("Recorded")


def format_time(timestamp_ms: int) -> str:
    return time.strftime("%H:%M:%S UTC", time.gmtime(timestamp_ms / 1000))
