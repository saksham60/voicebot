from __future__ import annotations

from fastapi import Request, WebSocket
from twilio.request_validator import RequestValidator

from app.config import Settings


def _public_url(base_url: str, path: str, query: str | None = None) -> str:
    url = f"{base_url.rstrip('/')}{path}"
    if query:
        return f"{url}?{query}"
    return url


async def validate_http_request(request: Request, settings: Settings) -> bool:
    if not settings.twilio_validate_requests or not settings.twilio_auth_token:
        return True
    signature = request.headers.get("X-Twilio-Signature", "")
    form = await request.form()
    params = {key: value for key, value in form.multi_items()}
    validator = RequestValidator(settings.twilio_auth_token)
    url = _public_url(settings.public_base_url, request.url.path, request.url.query)
    return validator.validate(url, params, signature)


def validate_websocket_request(websocket: WebSocket, settings: Settings) -> bool:
    if not settings.twilio_validate_requests or not settings.twilio_auth_token:
        return True
    signature = websocket.headers.get("x-twilio-signature", "")
    validator = RequestValidator(settings.twilio_auth_token)
    url = _public_url(settings.public_base_url, websocket.url.path, websocket.url.query)
    return validator.validate(url, {}, signature)
