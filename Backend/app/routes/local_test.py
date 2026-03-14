from __future__ import annotations

import json
import logging
from textwrap import dedent
from typing import Any
from uuid import uuid4

import aiohttp
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from app.models.call import CallSessionState, TranscriptSpeaker
from app.prompts.receptionist import build_receptionist_prompt
from app.services.tool_executor import RealtimeToolExecutor
from app.utils.logging import log_event

router = APIRouter(prefix="/local-test", tags=["local-test"])
logger = logging.getLogger("hotel_receptionist.local_test")


class LocalTranscriptPayload(BaseModel):
    session_id: str
    speaker: TranscriptSpeaker
    text: str


class LocalToolPayload(BaseModel):
    session_id: str
    tool_call: dict[str, Any]


class LocalCompletePayload(BaseModel):
    session_id: str
    reason: str | None = None


def _build_tool_executor(request: Request) -> RealtimeToolExecutor:
    return RealtimeToolExecutor(
        store=request.app.state.store,
        booking_provider=request.app.state.booking_provider,
        crm_client=request.app.state.crm_client,
        transfer_service=request.app.state.transfer_service,
        logger=logger,
    )


@router.get("", response_class=HTMLResponse)
async def local_test_page(request: Request) -> HTMLResponse:
    settings = request.app.state.settings
    page_config = {
        "sessionEndpoint": "/local-test/session",
        "transcriptEndpoint": "/local-test/transcript",
        "toolEndpoint": "/local-test/tool",
        "completeEndpoint": "/local-test/complete",
        "model": settings.openai_realtime_model,
        "voice": settings.openai_realtime_voice,
        "hotelName": settings.hotel_name,
    }

    html = dedent(
        f"""
        <!doctype html>
        <html lang="en">
        <head>
          <meta charset="utf-8" />
          <meta name="viewport" content="width=device-width, initial-scale=1" />
          <title>{settings.hotel_name} Local Voice Test</title>
          <style>
            :root {{
              --ink: #1c1a17;
              --muted: #6d6258;
              --paper: #f6efe3;
              --panel: #fffaf2;
              --accent: #9e3d1f;
              --accent-soft: #e8c9b7;
              --line: rgba(28, 26, 23, 0.12);
              --ok: #2e6a45;
            }}
            * {{ box-sizing: border-box; }}
            body {{
              margin: 0;
              font-family: "Bahnschrift", "Segoe UI", sans-serif;
              color: var(--ink);
              background:
                radial-gradient(circle at top right, rgba(158, 61, 31, 0.14), transparent 28%),
                linear-gradient(160deg, #f3e9da 0%, #f8f1e7 42%, #efe4d5 100%);
              min-height: 100vh;
            }}
            .shell {{
              max-width: 1100px;
              margin: 0 auto;
              padding: 32px 20px 48px;
            }}
            .hero {{
              display: grid;
              gap: 16px;
              margin-bottom: 24px;
            }}
            .eyebrow {{
              letter-spacing: 0.18em;
              text-transform: uppercase;
              font-size: 12px;
              color: var(--muted);
            }}
            h1 {{
              margin: 0;
              font-family: "Georgia", serif;
              font-size: clamp(2.3rem, 5vw, 4.4rem);
              line-height: 0.95;
              max-width: 10ch;
            }}
            .lede {{
              max-width: 68ch;
              color: var(--muted);
              font-size: 1.02rem;
            }}
            .grid {{
              display: grid;
              grid-template-columns: 320px 1fr;
              gap: 20px;
            }}
            .panel {{
              background: color-mix(in srgb, var(--panel) 92%, white 8%);
              border: 1px solid var(--line);
              border-radius: 22px;
              padding: 20px;
              box-shadow: 0 18px 60px rgba(32, 24, 18, 0.08);
            }}
            .card-title {{
              margin: 0 0 10px;
              font-size: 0.95rem;
              text-transform: uppercase;
              letter-spacing: 0.08em;
              color: var(--muted);
            }}
            .status {{
              display: inline-flex;
              align-items: center;
              gap: 8px;
              padding: 10px 12px;
              border-radius: 999px;
              background: var(--accent-soft);
              color: var(--accent);
              font-weight: 700;
            }}
            .status.ok {{
              background: rgba(46, 106, 69, 0.12);
              color: var(--ok);
            }}
            .controls {{
              display: grid;
              gap: 10px;
              margin-top: 16px;
            }}
            button {{
              appearance: none;
              border: 0;
              border-radius: 14px;
              padding: 14px 16px;
              font: inherit;
              font-weight: 700;
              cursor: pointer;
              transition: transform 150ms ease, opacity 150ms ease, box-shadow 150ms ease;
            }}
            button:hover {{ transform: translateY(-1px); }}
            button:disabled {{ opacity: 0.45; cursor: not-allowed; transform: none; }}
            .primary {{
              background: var(--accent);
              color: white;
              box-shadow: 0 12px 30px rgba(158, 61, 31, 0.25);
            }}
            .secondary {{
              background: rgba(28, 26, 23, 0.08);
              color: var(--ink);
            }}
            .tips {{
              display: grid;
              gap: 10px;
              margin-top: 18px;
              color: var(--muted);
              font-size: 0.95rem;
            }}
            .transcript {{
              display: grid;
              gap: 12px;
              min-height: 440px;
              max-height: 65vh;
              overflow: auto;
              padding-right: 6px;
            }}
            .turn {{
              border: 1px solid var(--line);
              border-radius: 18px;
              padding: 14px 16px;
              background: rgba(255, 255, 255, 0.72);
            }}
            .turn.assistant {{
              background: rgba(158, 61, 31, 0.08);
              border-color: rgba(158, 61, 31, 0.22);
            }}
            .turn.caller {{
              background: rgba(28, 26, 23, 0.05);
            }}
            .label {{
              display: block;
              margin-bottom: 6px;
              font-size: 0.8rem;
              text-transform: uppercase;
              letter-spacing: 0.08em;
              color: var(--muted);
            }}
            .log {{
              margin-top: 16px;
              padding-top: 14px;
              border-top: 1px solid var(--line);
              color: var(--muted);
              font-size: 0.92rem;
              white-space: pre-wrap;
            }}
            code {{
              font-family: Consolas, monospace;
              font-size: 0.92em;
            }}
            @media (max-width: 900px) {{
              .grid {{ grid-template-columns: 1fr; }}
              h1 {{ max-width: none; }}
            }}
          </style>
        </head>
        <body>
          <div class="shell">
            <section class="hero">
              <div class="eyebrow">Local Browser Voice Test</div>
              <h1>{settings.hotel_name} Receptionist</h1>
              <div class="lede">
                This browser test now saves transcripts and booking fields into the same SQLite database as the Twilio flow. You can inspect them through the bookings endpoint after the conversation.
              </div>
            </section>

            <section class="grid">
              <div class="panel">
                <p class="card-title">Connection</p>
                <div id="status" class="status">Idle</div>
                <div class="controls">
                  <button id="startBtn" class="primary">Start Mic Test</button>
                  <button id="stopBtn" class="secondary" disabled>Stop Session</button>
                </div>
                <div class="tips">
                  <div>Use Chrome or Edge on localhost and allow microphone access.</div>
                  <div>The assistant will greet you first and start the reservation flow.</div>
                  <div>Your booking details will be saved in SQLite and listed at <code>/bookings</code>.</div>
                </div>
                <div id="log" class="log">Waiting to start.</div>
              </div>

              <div class="panel">
                <p class="card-title">Transcript</p>
                <div id="transcript" class="transcript"></div>
              </div>
            </section>

            <audio id="remoteAudio" autoplay></audio>
            <script id="page-config" type="application/json">{json.dumps(page_config)}</script>
            <script>
              const config = JSON.parse(document.getElementById("page-config").textContent);
              const statusEl = document.getElementById("status");
              const logEl = document.getElementById("log");
              const transcriptEl = document.getElementById("transcript");
              const startBtn = document.getElementById("startBtn");
              const stopBtn = document.getElementById("stopBtn");
              const remoteAudio = document.getElementById("remoteAudio");

              let pc = null;
              let dc = null;
              let localStream = null;
              let sessionId = null;
              let shouldAutoStop = false;

              function setStatus(text, ok = false) {{
                statusEl.textContent = text;
                statusEl.classList.toggle("ok", ok);
              }}

              function setLog(text) {{
                logEl.textContent = text;
              }}

              function addTurn(role, text) {{
                if (!text) return;
                const item = document.createElement("div");
                item.className = `turn ${{role.toLowerCase()}}`;
                item.innerHTML = `<span class="label">${{role}}</span>${{text}}`;
                transcriptEl.appendChild(item);
                transcriptEl.scrollTop = transcriptEl.scrollHeight;
              }}

              function resetUi() {{
                startBtn.disabled = false;
                stopBtn.disabled = true;
                setStatus("Idle");
              }}

              async function postJson(url, payload) {{
                const response = await fetch(url, {{
                  method: "POST",
                  headers: {{ "Content-Type": "application/json" }},
                  body: JSON.stringify(payload),
                  keepalive: true,
                }});
                const data = await response.json().catch(() => ({{}}));
                if (!response.ok) {{
                  throw new Error(data.detail ? JSON.stringify(data.detail) : `Request failed: ${{response.status}}`);
                }}
                return data;
              }}

              async function persistTranscript(speaker, text) {{
                if (!sessionId || !text) return;
                try {{
                  await postJson(config.transcriptEndpoint, {{
                    session_id: sessionId,
                    speaker,
                    text,
                  }});
                }} catch (error) {{
                  console.warn("Transcript persistence failed", error);
                }}
              }}

              async function handleFunctionCalls(outputItems) {{
                const functionCalls = outputItems.filter((item) => item.type === "function_call");
                if (!functionCalls.length) {{
                  if (shouldAutoStop) {{
                    shouldAutoStop = false;
                    setTimeout(() => {{
                      stopSession("Local browser session completed");
                    }}, 900);
                  }}
                  return;
                }}

                let closeAfterResponse = false;
                for (const toolCall of functionCalls) {{
                  const toolResult = await postJson(config.toolEndpoint, {{
                    session_id: sessionId,
                    tool_call: toolCall,
                  }});
                  closeAfterResponse = closeAfterResponse || toolResult.close_after_response;
                  dc.send(JSON.stringify({{
                    type: "conversation.item.create",
                    item: {{
                      type: "function_call_output",
                      call_id: toolResult.call_id,
                      output: JSON.stringify(toolResult.output),
                    }},
                  }}));
                }}

                dc.send(JSON.stringify({{
                  type: "response.create",
                  response: {{ modalities: ["audio", "text"] }},
                }}));
                shouldAutoStop = closeAfterResponse;
              }}

              async function stopSession(reason = "Local browser session stopped") {{
                try {{
                  if (sessionId) {{
                    await fetch(config.completeEndpoint, {{
                      method: "POST",
                      headers: {{ "Content-Type": "application/json" }},
                      body: JSON.stringify({{ session_id: sessionId, reason }}),
                      keepalive: true,
                    }});
                  }}
                  if (dc) dc.close();
                  if (pc) pc.close();
                  if (localStream) {{
                    localStream.getTracks().forEach((track) => track.stop());
                  }}
                }} finally {{
                  pc = null;
                  dc = null;
                  localStream = null;
                  sessionId = null;
                  shouldAutoStop = false;
                  remoteAudio.srcObject = null;
                  resetUi();
                  setLog("Session stopped.");
                }}
              }}

              async function startSession() {{
                startBtn.disabled = true;
                stopBtn.disabled = false;
                transcriptEl.innerHTML = "";
                setStatus("Requesting microphone...");
                setLog("Opening microphone and creating a persisted local booking session...");

                try {{
                  localStream = await navigator.mediaDevices.getUserMedia({{ audio: true }});
                  const sessionData = await postJson(config.sessionEndpoint, {{}});
                  sessionId = sessionData.session_id;

                  pc = new RTCPeerConnection();
                  pc.ontrack = (event) => {{
                    remoteAudio.srcObject = event.streams[0];
                  }};

                  localStream.getTracks().forEach((track) => pc.addTrack(track, localStream));
                  dc = pc.createDataChannel("oai-events");
                  dc.addEventListener("open", () => {{
                    setStatus("Connected", true);
                    setLog(`Realtime connection established. Session: ${{sessionId}}`);
                    dc.send(JSON.stringify({{
                      type: "session.update",
                      session: {{
                        instructions: sessionData.instructions,
                        tools: sessionData.tools,
                        tool_choice: "auto",
                        modalities: ["audio", "text"],
                        voice: sessionData.voice,
                        input_audio_transcription: {{ model: sessionData.transcription_model }},
                        turn_detection: {{ type: "server_vad" }}
                      }}
                    }}));
                    dc.send(JSON.stringify({{
                      type: "response.create",
                      response: {{
                        modalities: ["audio", "text"],
                        instructions: "Begin the call now for Hotel Oman only. Do not ask for city, branch, property, area, or location. Greet the caller professionally, confirm this is for Hotel Oman, and ask for the check-in date."
                      }}
                    }}));
                  }});

                  dc.addEventListener("message", async (event) => {{
                    const message = JSON.parse(event.data);
                    if (message.type === "conversation.item.input_audio_transcription.completed" && message.transcript) {{
                      addTurn("Caller", message.transcript);
                      await persistTranscript("caller", message.transcript);
                    }}
                    if (message.type === "response.output_audio_transcript.done" && message.transcript) {{
                      addTurn("Assistant", message.transcript);
                      await persistTranscript("assistant", message.transcript);
                    }}
                    if (message.type === "response.done") {{
                      await handleFunctionCalls(message.response?.output || []);
                    }}
                    if (message.type === "error") {{
                      setStatus("Error");
                      setLog("Realtime error: " + JSON.stringify(message.error || message));
                    }}
                  }});

                  const offer = await pc.createOffer();
                  await pc.setLocalDescription(offer);

                  const sdpResponse = await fetch(`https://api.openai.com/v1/realtime?model=${{encodeURIComponent(sessionData.model)}}`, {{
                    method: "POST",
                    body: offer.sdp,
                    headers: {{
                      Authorization: `Bearer ${{sessionData.client_secret}}`,
                      "Content-Type": "application/sdp"
                    }}
                  }});

                  const answerSdp = await sdpResponse.text();
                  if (!sdpResponse.ok) {{
                    throw new Error(answerSdp);
                  }}
                  await pc.setRemoteDescription({{ type: "answer", sdp: answerSdp }});
                }} catch (error) {{
                  await stopSession("Local browser session failed");
                  setStatus("Failed");
                  setLog(error.message || String(error));
                }}
              }}

              startBtn.addEventListener("click", startSession);
              stopBtn.addEventListener("click", () => stopSession());
              window.addEventListener("beforeunload", () => {{
                if (!sessionId) return;
                const payload = JSON.stringify({{ session_id: sessionId, reason: "Browser tab closed" }});
                navigator.sendBeacon(config.completeEndpoint, new Blob([payload], {{ type: "application/json" }}));
              }});
            </script>
          </div>
        </body>
        </html>
        """
    ).strip()

    return HTMLResponse(html)


@router.post("/session")
async def create_local_test_session(request: Request) -> dict[str, Any]:
    settings = request.app.state.settings
    if not settings.openai_api_key or settings.openai_api_key.startswith("sk-your-openai-key"):
        raise HTTPException(
            status_code=400,
            detail="OPENAI_API_KEY is not configured in the backend .env file.",
        )

    session_id = f"LOCAL_{uuid4().hex[:12].upper()}"
    local_session = CallSessionState(
        call_sid=session_id,
        hotel_name=settings.hotel_name,
        from_number="local-browser-mic",
        to_number=settings.hotel_phone_number or settings.hotel_name,
        call_status="local_test_connected",
        metadata={
            "channel": "local_test",
            "transport": "browser_webrtc",
        },
    )
    await request.app.state.store.upsert_call(local_session)

    payload = {
        "model": settings.openai_realtime_model,
        "voice": settings.openai_realtime_voice,
    }
    headers = {
        "Authorization": f"Bearer {settings.openai_api_key}",
        "Content-Type": "application/json",
    }

    timeout = aiohttp.ClientTimeout(total=settings.request_timeout_seconds)
    async with aiohttp.ClientSession(timeout=timeout) as client:
        async with client.post(
            "https://api.openai.com/v1/realtime/sessions",
            headers=headers,
            json=payload,
        ) as response:
            raw_body = await response.text()
            try:
                data = json.loads(raw_body)
            except json.JSONDecodeError:
                data = {"raw": raw_body}

    if response.status >= 400:
        raise HTTPException(status_code=response.status, detail=data)

    client_secret = data.get("client_secret", {}).get("value")
    if not client_secret:
        raise HTTPException(
            status_code=500,
            detail="OpenAI Realtime session response did not contain a client_secret.",
        )

    tool_executor = _build_tool_executor(request)
    log_event(logger, "local_test.session_created", call_sid=session_id)
    return {
        "session_id": session_id,
        "client_secret": client_secret,
        "model": settings.openai_realtime_model,
        "voice": settings.openai_realtime_voice,
        "transcription_model": settings.openai_transcription_model,
        "instructions": build_receptionist_prompt(settings, include_tools=True),
        "tools": tool_executor.tool_definitions,
    }


@router.post("/transcript")
async def persist_local_test_transcript(
    payload: LocalTranscriptPayload, request: Request
) -> dict[str, str]:
    settings = request.app.state.settings
    session = await request.app.state.store.load_call_session(
        payload.session_id, settings.hotel_name
    )
    if session is None:
        raise HTTPException(status_code=404, detail="Local test session not found.")

    session.add_transcript(payload.speaker, payload.text)
    await request.app.state.store.upsert_call(session)
    return {"status": "ok"}


@router.post("/tool")
async def execute_local_test_tool(
    payload: LocalToolPayload, request: Request
) -> dict[str, Any]:
    settings = request.app.state.settings
    session = await request.app.state.store.load_call_session(
        payload.session_id, settings.hotel_name
    )
    if session is None:
        raise HTTPException(status_code=404, detail="Local test session not found.")

    tool_executor = _build_tool_executor(request)
    result = await tool_executor.execute(session, payload.tool_call)
    session.add_transcript(
        TranscriptSpeaker.TOOL,
        f"{payload.tool_call.get('name')}: {json.dumps(result.output)}",
    )
    await request.app.state.store.upsert_call(session)
    return {
        "call_id": result.call_id,
        "output": result.output,
        "close_after_response": result.close_after_response,
    }


@router.post("/complete")
async def complete_local_test_session(
    payload: LocalCompletePayload, request: Request
) -> dict[str, str]:
    settings = request.app.state.settings
    session = await request.app.state.store.load_call_session(
        payload.session_id, settings.hotel_name
    )
    if session is None:
        raise HTTPException(status_code=404, detail="Local test session not found.")

    if session.call_status != "completed":
        session.finalize(payload.reason or session.end_reason)
        await request.app.state.store.upsert_call(session)
        log_event(
            logger,
            "local_test.completed",
            call_sid=session.call_sid,
            booking_status=session.booking_status.value,
        )
    return {"status": "ok"}

