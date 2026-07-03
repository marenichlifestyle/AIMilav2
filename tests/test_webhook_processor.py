from __future__ import annotations

import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import patch

from app import repositories
from app.services import webhook_processor as wp


class ChatAppPayloadParsingTest(unittest.TestCase):
    def test_multiline_message_is_preserved(self) -> None:
        parsed = wp.extract_chatapp_payload(
            {
                "body": {
                    "sender": "None",
                    "id_chat": "chat-1",
                    "message": "Добрый день\nинтересует Bentley Continental GT",
                    "file_or_message": "Добрый день\nинтересует Bentley Continental GT",
                }
            }
        )

        self.assertEqual(parsed["message"], "Добрый день\nинтересует Bentley Continental GT")
        self.assertEqual(parsed["message_fields"], ["message"])

    def test_longer_file_or_message_wins_when_message_is_shorter(self) -> None:
        parsed = wp.extract_chatapp_payload(
            {
                "body": {
                    "sender": "None",
                    "id_chat": "chat-1",
                    "message": "Добрый день",
                    "file_or_message": "Добрый день\nинтересует Bentley Continental GT",
                }
            }
        )

        self.assertEqual(parsed["message"], "Добрый день\nинтересует Bentley Continental GT")
        self.assertEqual(parsed["message_fields"], ["file_or_message"])

    def test_file_or_message_url_is_used_as_file_link(self) -> None:
        parsed = wp.extract_chatapp_payload(
            {
                "body": {
                    "sender": "None",
                    "id_chat": "chat-1",
                    "message": "",
                    "file_or_message": "https://cdn.example.com/voice.oga",
                    "file_in_message": "True",
                }
            }
        )

        self.assertEqual(parsed["message"], "")
        self.assertEqual(parsed["file_link"], "https://cdn.example.com/voice.oga")

    def test_own_identity_is_detected_even_with_sender_none(self) -> None:
        parsed = wp.extract_chatapp_payload(
            {
                "body": {
                    "sender": "None",
                    "id_chat": "chat-1",
                    "username": "MillionMilesMila",
                    "name": "Million Miles | Менеджер",
                    "message": "Добрый день. Меня зовут Мила.",
                }
            }
        )

        self.assertTrue(wp.has_own_identity(parsed))

    def test_client_named_mila_is_not_treated_as_own_identity(self) -> None:
        parsed = wp.extract_chatapp_payload(
            {
                "body": {
                    "sender": "None",
                    "id_chat": "chat-1",
                    "username": "real_client",
                    "name": "Мила",
                    "message": "Здравствуйте, хочу G63",
                }
            }
        )

        self.assertFalse(wp.has_own_identity(parsed))

    def test_recent_outgoing_echo_is_detected(self) -> None:
        self.assertTrue(wp.is_echo_of_recent_outgoing("Добрый день.\n\nТест", ["Добрый день. Тест"]))
        self.assertFalse(wp.is_echo_of_recent_outgoing("Новый вопрос", ["Добрый день. Тест"]))


class _FakeSession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def commit(self) -> None:
        return None

    async def rollback(self) -> None:
        return None


class WebhookHandoffTest(unittest.IsolatedAsyncioTestCase):
    async def test_manager_handoff_message_is_saved_and_does_not_acquire_processing(self) -> None:
        client = SimpleNamespace(
            id=uuid.uuid4(),
            chatapp_chat_id="chat-1",
            ai_state=repositories.AI_STATE_MANAGER_HANDOFF,
        )
        created_messages: list[dict] = []

        async def fake_get_or_create_client(**kwargs):
            return client

        async def fake_recent(*args, **kwargs):
            return []

        async def fake_create_message(**kwargs):
            created_messages.append(kwargs)
            return SimpleNamespace(id=uuid.uuid4())

        async def fail_acquire(*args, **kwargs):
            raise AssertionError("processing must not be acquired for manager_handoff")

        processor = wp.WebhookProcessor(object(), object(), object(), object())

        with patch.object(wp, "SessionLocal", lambda: _FakeSession()), \
            patch.object(wp.repositories, "get_or_create_client", fake_get_or_create_client), \
            patch.object(wp.repositories, "get_recent_outgoing_texts", fake_recent), \
            patch.object(wp.repositories, "create_message", fake_create_message), \
            patch.object(wp.repositories, "try_acquire_processing", fail_acquire):
            await processor.handle_webhook(
                {
                    "body": {
                        "sender": "None",
                        "id_chat": "chat-1",
                        "username": "client",
                        "name": "Client",
                        "message": "А можно еще вопрос?",
                    }
                }
            )

        self.assertEqual(len(created_messages), 1)
        self.assertTrue(created_messages[0]["processed"])
        self.assertEqual(created_messages[0]["ignored_reason"], "manager_handoff")

    async def test_own_echo_message_is_saved_and_does_not_acquire_processing(self) -> None:
        client = SimpleNamespace(
            id=uuid.uuid4(),
            chatapp_chat_id="chat-1",
            ai_state=repositories.AI_STATE_ACTIVE,
        )
        created_messages: list[dict] = []

        async def fake_get_or_create_client(**kwargs):
            return client

        async def fake_create_message(**kwargs):
            created_messages.append(kwargs)
            return SimpleNamespace(id=uuid.uuid4())

        async def fail_acquire(*args, **kwargs):
            raise AssertionError("processing must not be acquired for echo")

        processor = wp.WebhookProcessor(object(), object(), object(), object())

        with patch.object(wp, "SessionLocal", lambda: _FakeSession()), \
            patch.object(wp.repositories, "get_or_create_client", fake_get_or_create_client), \
            patch.object(wp.repositories, "create_message", fake_create_message), \
            patch.object(wp.repositories, "try_acquire_processing", fail_acquire):
            await processor.handle_webhook(
                {
                    "body": {
                        "sender": "None",
                        "id_chat": "chat-1",
                        "username": "MillionMilesMila",
                        "name_chat": "Million Miles | Менеджер",
                        "message": "Добрый день. Меня зовут Мила.",
                    }
                }
            )

        self.assertEqual(len(created_messages), 1)
        self.assertTrue(created_messages[0]["processed"])
        self.assertEqual(created_messages[0]["ignored_reason"], "non_client_or_echo")


if __name__ == "__main__":
    unittest.main()
