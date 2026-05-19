import unittest

from app.openai_service import _extract_text_from_response, is_technical_json_text


class OpenAIResponseTextExtractionTest(unittest.TestCase):
    def test_extract_text_uses_last_safe_message_after_json_chunks(self) -> None:
        response = {
            "output": [
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": '{"query":"Lamborghini Urus","criteria":{"brand":"Lamborghini"}}',
                        }
                    ],
                },
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": '{"reason":"Нужен менеджер","summary":"Клиент просит точный статус"}',
                        }
                    ],
                },
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": "Дмитрий, передам вопрос ответственному менеджеру, он подтвердит наличие.",
                        }
                    ],
                },
            ]
        }

        self.assertEqual(
            _extract_text_from_response(response),
            "Дмитрий, передам вопрос ответственному менеджеру, он подтвердит наличие.",
        )

    def test_extract_text_returns_empty_when_only_json_messages(self) -> None:
        response = {
            "output": [
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": '{"query":"Lamborghini Urus","criteria":{"brand":"Lamborghini"}}',
                        }
                    ],
                }
            ]
        }

        self.assertEqual(_extract_text_from_response(response), "")

    def test_extract_text_returns_normal_output_text(self) -> None:
        response = {"output_text": "Здравствуйте. Подскажите, какой автомобиль рассматриваете?"}

        self.assertEqual(
            _extract_text_from_response(response),
            "Здравствуйте. Подскажите, какой автомобиль рассматриваете?",
        )

    def test_technical_json_detection(self) -> None:
        self.assertTrue(is_technical_json_text('{"query":"x","criteria":{}}'))
        self.assertTrue(is_technical_json_text('[{"query":"x"}]'))
        self.assertFalse(is_technical_json_text("Обычный текст для клиента."))


if __name__ == "__main__":
    unittest.main()
