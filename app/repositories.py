from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import and_, exists, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Client, ManagerEscalation, Message


async def get_or_create_client(
    session: AsyncSession,
    chatapp_chat_id: str,
    username: str | None,
    name: str | None,
    messenger_type: str,
) -> Client:
    upsert_base = insert(Client).values(
        chatapp_chat_id=chatapp_chat_id,
        username=username,
        name=name,
        messenger_type=messenger_type,
    )
    stmt = upsert_base.on_conflict_do_update(
        index_elements=[Client.chatapp_chat_id],
        set_={
            "username": func.coalesce(upsert_base.excluded.username, Client.username),
            "name": func.coalesce(upsert_base.excluded.name, Client.name),
            "messenger_type": func.coalesce(upsert_base.excluded.messenger_type, Client.messenger_type),
            "updated_at": func.now(),
        },
    ).returning(Client.id)
    result = await session.execute(stmt)
    client_id = result.scalar_one()
    client = await session.get(Client, client_id)
    if client is None:
        raise RuntimeError("Failed to fetch client after upsert")
    return client


async def create_message(
    session: AsyncSession,
    client_id: uuid.UUID,
    direction: str,
    text: str | None,
    file_url: str | None,
    file_type: str | None,
    raw_payload: dict[str, Any] | None,
    processed: bool,
) -> Message:
    message = Message(
        client_id=client_id,
        direction=direction,
        text=text,
        file_url=file_url,
        file_type=file_type,
        raw_payload=raw_payload,
        processed=processed,
    )
    session.add(message)
    await session.flush()
    return message


async def try_acquire_processing(session: AsyncSession, client_id: uuid.UUID) -> bool:
    stmt = (
        update(Client)
        .where(and_(Client.id == client_id, Client.processing.is_(False)))
        .values(processing=True, updated_at=func.now())
        .returning(Client.id)
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none() is not None


async def set_client_processing(
    session: AsyncSession,
    client_id: uuid.UUID,
    value: bool,
) -> None:
    stmt = (
        update(Client)
        .where(Client.id == client_id)
        .values(processing=value, updated_at=func.now())
    )
    await session.execute(stmt)


async def try_release_processing_if_queue_empty(
    session: AsyncSession,
    client_id: uuid.UUID,
) -> bool:
    pending_incoming = exists(
        select(1).where(
            and_(
                Message.client_id == client_id,
                Message.direction == "incoming",
                Message.processed.is_(False),
            )
        )
    )
    stmt = (
        update(Client)
        .where(and_(Client.id == client_id, ~pending_incoming))
        .values(processing=False, updated_at=func.now())
        .returning(Client.id)
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none() is not None


async def set_client_last_response_id(
    session: AsyncSession,
    client_id: uuid.UUID,
    response_id: str | None,
) -> None:
    stmt = (
        update(Client)
        .where(Client.id == client_id)
        .values(last_openai_response_id=response_id, updated_at=func.now())
    )
    await session.execute(stmt)


async def get_client_by_id(session: AsyncSession, client_id: uuid.UUID) -> Client | None:
    query = select(Client).where(Client.id == client_id).limit(1)
    result = await session.execute(query)
    return result.scalar_one_or_none()


async def get_unprocessed_incoming_messages(session: AsyncSession, client_id: uuid.UUID) -> list[Message]:
    query = (
        select(Message)
        .where(
            and_(
                Message.client_id == client_id,
                Message.direction == "incoming",
                Message.processed.is_(False),
            )
        )
        .order_by(Message.created_at.asc())
    )
    result = await session.execute(query)
    return list(result.scalars().all())


async def mark_messages_processed(session: AsyncSession, message_ids: list[uuid.UUID]) -> None:
    if not message_ids:
        return
    stmt = update(Message).where(Message.id.in_(message_ids)).values(processed=True)
    await session.execute(stmt)


async def create_manager_escalation(
    session: AsyncSession,
    client_id: uuid.UUID,
    reason: str,
    summary: str,
) -> ManagerEscalation:
    escalation = ManagerEscalation(
        client_id=client_id,
        reason=reason,
        summary=summary,
        status="new",
    )
    session.add(escalation)
    await session.flush()
    return escalation
