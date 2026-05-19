# ChatApp Mila (Python replacement)

Рабочий сервис на FastAPI для замены n8n workflow `ChatApp Mila`.

## Что делает
- Принимает webhook: `POST /webhook/chatapp`
- Безопасно парсит поля ChatApp payload
- Игнорирует сообщения не от клиента (`employee/manager/system/bot`)
- Хранит клиентов и сообщения в локальной PostgreSQL
- Делает антидубль без Redis/Celery (`processing + delay + batch`)
- Обрабатывает текст, голосовые и фото
- Использует OpenAI Responses API с `previous_response_id`
- Ищет авто в Supabase `public."CMExpert"` через `car_search`
- Эскалирует менеджеру в Telegram через `get_manager`
- Отправляет ответ в ChatApp API
- Никогда не роняет webhook наружу 500 (возвращает 200 OK)

## 1) Заполнение `.env`
```bash
cp .env.example .env
```

Заполните обязательные поля:
- `OPENAI_API_KEY`
- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`
- `TELEGRAM_BOT_TOKEN`

Остальные значения можно оставить по умолчанию.

## 2) Запуск
```bash
docker compose up -d --build
```

## 3) Проверка health
```bash
curl http://localhost:8000/health
```
Ожидаемый ответ:
```json
{"status":"ok"}
```

## 4) HTTPS через ngrok
```bash
ngrok http 8000
```

## 5) URL для ChatApp webhook
Используйте URL формата:
```text
https://xxxx.ngrok-free.app/webhook/chatapp
```

Локально webhook:
```text
http://localhost:8000/webhook/chatapp
```

## 6) Логи
```bash
docker compose logs -f app
```

## Важные env
- `OPENAI_MODEL=gpt-5.4-mini` (можно переключить на `gpt-5.5`)
- `OPENAI_TRANSCRIBE_MODEL=whisper-1`
- `CHATAPP_DEFAULT_LICENSE_ID=68179`
- `CHATAPP_DEFAULT_MESSENGER=telegram`
- `PROCESSING_DELAY_SECONDS=12`
- `MAX_MEDIA_MB=20`

## Таблицы
Таблицы создаются автоматически при старте приложения:
- `clients`
- `messages`
- `manager_escalations`

## Поведение при ошибках
- Любые ошибки OpenAI/Supabase/ChatApp/Telegram логируются
- Флаг `client.processing` сбрасывается в `false` в `finally`
- Webhook всегда отвечает `200 OK`
