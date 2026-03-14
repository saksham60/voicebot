from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request, Response, WebSocket
from twilio.twiml.voice_response import Connect, VoiceResponse

from app.models.booking import BookingStatus
from app.models.call import CallSessionState
from app.services.realtime_bridge import RealtimeCallBridge
from app.utils.logging import log_event
from app.utils.twilio import validate_http_request, validate_websocket_request

router = APIRouter(prefix="/twilio", tags=["twilio"])
logger = logging.getLogger("hotel_receptionist.twilio")


@router.post("/voice")
async def inbound_voice_webhook(request: Request) -> Response:
    settings = request.app.state.settings
    if not await validate_http_request(request, settings):
        raise HTTPException(status_code=403, detail="Invalid Twilio signature")

    form = await request.form()
    call_sid = str(form.get("CallSid", "")).strip()
    from_number = str(form.get("From", "")).strip()
    to_number = str(form.get("To", "")).strip()

    session = CallSessionState(
        call_sid=call_sid,
        hotel_name=settings.hotel_name,
        from_number=from_number,
        to_number=to_number,
        call_status="initiated",
    )
    await request.app.state.store.upsert_call(session)

    response = VoiceResponse()
    connect = Connect(action=settings.twilio_post_connect_url, method="POST")
    connect.stream(url=settings.twilio_media_stream_url)
    response.append(connect)

    log_event(
        logger,
        "call.webhook_received",
        call_sid=call_sid,
        from_number=from_number,
        to_number=to_number,
        media_stream_url=settings.twilio_media_stream_url,
    )
    return Response(content=str(response), media_type="application/xml")


@router.post("/status")
async def call_status_callback(request: Request) -> dict[str, str]:
    settings = request.app.state.settings
    if not await validate_http_request(request, settings):
        raise HTTPException(status_code=403, detail="Invalid Twilio signature")

    form = await request.form()
    call_sid = str(form.get("CallSid", "")).strip()
    call_status = str(form.get("CallStatus", "")).strip()
    existing = await request.app.state.store.get_call(call_sid)

    if existing is not None:
        session = CallSessionState(
            call_sid=call_sid,
            hotel_name=settings.hotel_name,
            stream_sid=existing.get("stream_sid"),
            from_number=existing.get("from_number"),
            to_number=existing.get("to_number"),
            call_status=call_status or existing.get("call_status", "unknown"),
            booking_status=BookingStatus(existing.get("booking_status", "in_progress")),
            handoff_requested=existing.get("handoff_requested", False),
            handoff_reason=existing.get("handoff_reason"),
            end_reason=existing.get("end_reason"),
            started_at=existing.get("started_at"),
            ended_at=existing.get("ended_at"),
            metadata=existing.get("metadata", {}),
        )
        session.booking.guest_name = existing.get("guest_name")
        session.booking.check_in_date = existing.get("check_in_date")
        session.booking.nights = existing.get("nights")
        session.booking.guests = existing.get("guests")
        session.booking.room_type = existing.get("room_type")
        session.booking.phone_number_if_provided = existing.get("phone_number_if_provided")
        session.booking.special_requests = existing.get("special_requests")
        for transcript in existing.get("transcripts", []):
            speaker = transcript.get("speaker")
            text = transcript.get("text", "")
            if speaker and text:
                session.add_transcript(speaker, text)
        await request.app.state.store.upsert_call(session)

    log_event(
        logger,
        "call.status_callback",
        call_sid=call_sid,
        call_status=call_status,
    )
    return {"status": "ok"}


@router.post("/post-connect")
async def post_connect_handler(request: Request) -> Response:
    settings = request.app.state.settings
    if not await validate_http_request(request, settings):
        raise HTTPException(status_code=403, detail="Invalid Twilio signature")

    form = await request.form()
    call_sid = str(form.get("CallSid", "")).strip()
    call_data = await request.app.state.store.get_call(call_sid)

    response = VoiceResponse()
    if call_data and call_data.get("handoff_requested") and settings.call_transfer_enabled:
        response.say("Please hold while I connect you to a hotel staff member.")
        response.dial(settings.twilio_transfer_number)
    elif call_data and call_data.get("booking_status") == BookingStatus.CONFIRMED.value:
        response.say(
            "Thank you for calling. Your reservation request has been recorded and hotel staff will follow up shortly. Goodbye."
        )
        response.hangup()
    elif call_data and call_data.get("handoff_requested"):
        response.say(
            "A hotel staff member will follow up with you shortly. Thank you for calling. Goodbye."
        )
        response.hangup()
    else:
        response.say("Thank you for calling. Goodbye.")
        response.hangup()

    log_event(
        logger,
        "call.post_connect",
        call_sid=call_sid,
        booking_status=call_data.get("booking_status") if call_data else None,
        handoff_requested=call_data.get("handoff_requested") if call_data else False,
    )
    return Response(content=str(response), media_type="application/xml")


@router.websocket("/media-stream")
async def media_stream(websocket: WebSocket) -> None:
    app = websocket.scope["app"]
    settings = app.state.settings
    if not validate_websocket_request(websocket, settings):
        await websocket.close(code=1008)
        return

    bridge = RealtimeCallBridge(
        settings=settings,
        store=app.state.store,
        booking_provider=app.state.booking_provider,
        crm_client=app.state.crm_client,
        transfer_service=app.state.transfer_service,
        logger=logging.getLogger("hotel_receptionist.realtime"),
    )
    await bridge.handle(websocket)
