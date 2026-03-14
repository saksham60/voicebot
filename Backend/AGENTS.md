# AGENTS.md

## Scope
- Work inside `Backend/` unless a task explicitly requires another area.
- This repo is a FastAPI backend for a Twilio + OpenAI Realtime hotel receptionist MVP.

## Stack
- Python 3.11+
- FastAPI for HTTP and WebSocket handling
- Twilio Voice Media Streams for inbound telephony
- OpenAI Realtime API for speech-to-speech responses
- SQLite for local persistence

## Engineering Rules
- Keep all configuration in `.env` and `app/config.py`.
- Do not hardcode hotel-specific values in routes or prompts.
- Keep integrations behind service classes so SQLite can later be replaced by CRM/PMS APIs.
- Prefer small, composable modules under `app/services/`.
- For OpenAI Realtime or Twilio Voice changes, verify official docs before changing event names or payload shapes.
- Do not invent booking availability or confirmation numbers in tests, prompts, or code paths.

## Useful Commands
- `python -m venv .venv`
- `.venv\Scripts\activate`
- `pip install -r requirements.txt`
- `uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload`
- `curl http://127.0.0.1:8000/healthz`

## Local Validation
- Test the health route before wiring Twilio.
- Test the voice webhook with a form POST before using ngrok.
- Keep `PUBLIC_BASE_URL` aligned with the active ngrok URL when request validation is enabled.
