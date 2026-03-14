# Hotel Digital Receptionist MVP

Production-minded MVP for an inbound hotel phone receptionist built with FastAPI, Twilio Voice Media Streams, and the OpenAI Realtime API.

## Project Tree

```text
Backend/
├── .env.example
├── AGENTS.md
├── README.md
├── requirements.txt
├── app/
│   ├── __init__.py
│   ├── config.py
│   ├── main.py
│   ├── models/
│   │   ├── __init__.py
│   │   ├── booking.py
│   │   └── call.py
│   ├── prompts/
│   │   ├── __init__.py
│   │   └── receptionist.py
│   ├── routes/
│   │   ├── __init__.py
│   │   ├── health.py
│   │   └── twilio.py
│   ├── services/
│   │   ├── __init__.py
│   │   ├── booking_provider.py
│   │   ├── call_transfer.py
│   │   ├── crm.py
│   │   ├── realtime_bridge.py
│   │   └── tool_executor.py
│   ├── storage/
│   │   ├── __init__.py
│   │   └── sqlite_store.py
│   └── utils/
│       ├── __init__.py
│       ├── logging.py
│       └── twilio.py
└── data/
    └── .gitkeep
```

## What It Does

- Accepts inbound Twilio calls through a webhook.
- Starts a Twilio Media Stream to your FastAPI WebSocket endpoint.
- Bridges Twilio audio to the OpenAI Realtime API using G.711 u-law audio, so no transcoding is required.
- Speaks back naturally with a hotel receptionist persona.
- Collects and stores:
  - `guest_name`
  - `check_in_date`
  - `nights`
  - `guests`
  - `room_type`
  - `phone_number_if_provided`
  - `special_requests`
- Confirms details before finalizing.
- Logs structured call events.
- Saves the final reservation request to local SQLite.
- Supports human handoff and incomplete booking outcomes.

## Requirements

- Python 3.11 or newer
- A Twilio account with a voice-capable phone number
- An OpenAI API key with Realtime access
- `ngrok` for local webhook exposure

## Setup

1. Open a terminal in `Backend/`.
2. Create and activate a virtual environment.

```powershell
python -m venv .venv
.venv\Scripts\activate
```

3. Install dependencies.

```powershell
pip install -r requirements.txt
```

4. Create your environment file.

```powershell
Copy-Item .env.example .env
```

5. Edit `.env` and set at least:
   - `OPENAI_API_KEY`
   - `PUBLIC_BASE_URL`
   - `TWILIO_ACCOUNT_SID`
   - `TWILIO_AUTH_TOKEN`
   - `TWILIO_TRANSFER_NUMBER` if you want live transfer after handoff

## Run Locally

Start the FastAPI server from `Backend/`:

```powershell
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Quick local checks:

```powershell
curl http://127.0.0.1:8000/healthz
curl -X POST http://127.0.0.1:8000/twilio/voice `
  -H "Content-Type: application/x-www-form-urlencoded" `
  -d "CallSid=CA1234567890&From=%2B14155550100&To=%2B14155550999"
```

The webhook response should return TwiML containing a `wss://.../twilio/media-stream` URL derived from `PUBLIC_BASE_URL`.

## ngrok Steps

Expose the local FastAPI app:

```powershell
ngrok http 8000
```

Copy the generated HTTPS forwarding URL and place it in `.env` as `PUBLIC_BASE_URL`, for example:

```text
PUBLIC_BASE_URL=https://bright-sky-1234.ngrok-free.app
```

Restart the FastAPI server after changing `.env`.

## Twilio Number Configuration

In the Twilio Console for your active phone number:

1. Go to `Phone Numbers` -> `Manage` -> `Active numbers`.
2. Open your hotel number.
3. Under `Voice Configuration`:
   - `A call comes in`
   - `Webhook`
   - URL: `https://YOUR-NGROK-DOMAIN.ngrok-free.app/twilio/voice`
   - Method: `HTTP POST`
4. Optional status callback:
   - URL: `https://YOUR-NGROK-DOMAIN.ngrok-free.app/twilio/status`
   - Method: `HTTP POST`
5. Save the number configuration.

## Call Flow

1. A caller dials the Twilio number.
2. Twilio sends `POST /twilio/voice`.
3. FastAPI returns TwiML with `<Connect><Stream>` to `/twilio/media-stream`.
4. Twilio opens a WebSocket and starts sending u-law audio frames.
5. The app opens an OpenAI Realtime WebSocket session using the configured model.
6. The app forwards Twilio audio to OpenAI and forwards OpenAI audio back to Twilio.
7. The system prompt drives the receptionist behavior:
   - greet the caller
   - ask one question at a time
   - collect booking details
   - confirm the summary
   - never invent availability
8. Realtime tool calls update structured booking fields in-process.
9. The session is stored in SQLite during the call and finalized when the call ends.
10. If human handoff is requested and `TWILIO_TRANSFER_NUMBER` is set, the app closes the media stream and Twilio dials the transfer number from `/twilio/post-connect`.

## Persistence

- SQLite database path: `data/calls.db`
- The `calls` table stores:
  - call metadata
  - booking status
  - extracted booking fields
  - transcript turns
  - handoff and completion state

## Local Test Instructions

Health check:

```powershell
curl http://127.0.0.1:8000/healthz
```

Simulate a Twilio voice webhook:

```powershell
curl -X POST http://127.0.0.1:8000/twilio/voice `
  -H "Content-Type: application/x-www-form-urlencoded" `
  -d "CallSid=CA_TEST_001&From=%2B14155550100&To=%2B14155550999"
```

Simulate a Twilio status callback:

```powershell
curl -X POST http://127.0.0.1:8000/twilio/status `
  -H "Content-Type: application/x-www-form-urlencoded" `
  -d "CallSid=CA_TEST_001&CallStatus=completed"
```

## Common Debugging Tips

- `403` on `/twilio/voice`:
  - Check `TWILIO_VALIDATE_REQUESTS`.
  - Confirm `PUBLIC_BASE_URL` exactly matches the public webhook URL Twilio is calling.
- Twilio connects but you hear silence:
  - Confirm `PUBLIC_BASE_URL` is HTTPS and the generated WebSocket URL is `wss://.../twilio/media-stream`.
  - Verify your OpenAI API key and Realtime model access.
- Audio sounds garbled:
  - Keep Twilio and OpenAI aligned on u-law audio.
  - This app uses `audio/pcmu` end-to-end to avoid transcoding.
- Calls end immediately after connect:
  - Check server logs for an OpenAI WebSocket connection error.
  - Make sure outbound network access to `api.openai.com` is available.
- Human transfer never happens:
  - Set `TWILIO_TRANSFER_NUMBER` in `.env`.
  - The transfer only occurs after the model requests a human handoff.
- Structured fields are missing:
  - Review the logs for tool execution events.
  - The model only finalizes fields it hears clearly.

## Deployment Path

This MVP is local-first but organized for straightforward cloud deployment:

- `app/config.py` is the single source of truth for environment configuration.
- `app/services/` isolates external integration points.
- `app/storage/sqlite_store.py` can be replaced by a managed database adapter.
- `app/routes/twilio.py` is already stateless at the HTTP layer.

## Next Steps for Production

- Replace SQLite with Postgres or Aurora.
- Add authenticated Twilio REST call updates for live transfer and supervisor controls.
- Add monitoring, trace IDs, and centralized log shipping.
- Add retry-safe CRM/PMS adapters with background jobs.
- Add per-hotel prompt and routing config.
- Add tests for webhook validation, tool execution, and call finalization.
