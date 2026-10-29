import json
import time
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

from .registry import Registry
from .providers import get_adapter

app = FastAPI()

PROFILES_DIR = Path(__file__).parent / "profiles"
DEFAULT_PROVIDER = "gpt"
DEFAULT_ACCOUNT = "default"

registry = Registry(PROFILES_DIR)


def clean_text(text: str) -> str:
    return (text or "").strip()


# ============================================================
# SESSION ENDPOINTS
# ============================================================


@app.post("/session/new")
async def new_session(request: Request):
    """
    Create-or-reset a session's tab. Existing session_id -> reset to a
    fresh chat (same lock object, old page closed, new page opened).
    Unseen session_id -> created fresh. Both paths go through
    AccountHandle.reset_session, the single owner of this logic.
    """
    try:
        body = await request.json()
        session_id = body.get("session_id", "code")
        account_name = body.get("account", DEFAULT_ACCOUNT)
        provider = body.get("provider", DEFAULT_PROVIDER)

        account = await registry.get_account(account_name)
        await account.reset_session(session_id, provider)

        return JSONResponse(content={
            "status": "cleared",
            "session_id": session_id,
            "account": account_name,
            "provider": provider,
        })
    except Exception as e:
        print("-> [SESSION] ERROR:", e)
        return JSONResponse(content={"status": "failed", "error": str(e)}, status_code=500)


@app.post("/session/use")
async def use_session(request: Request):
    """
    Switch a session's provider in place — same tab, same lock, just
    repointed at a different provider's site. Distinct from /session/new,
    which resets to a blank chat.
    """
    try:
        body = await request.json()
        session_id = body.get("session_id", "code")
        account_name = body.get("account", DEFAULT_ACCOUNT)
        provider = body.get("provider")
        if not provider:
            return JSONResponse(content={"status": "failed", "error": "provider required"}, status_code=400)

        account = await registry.get_account(account_name)
        await account.switch_provider(session_id, provider)

        return JSONResponse(content={
            "status": "switched",
            "session_id": session_id,
            "account": account_name,
            "provider": provider,
        })
    except Exception as e:
        print("-> [SESSION] ERROR:", e)
        return JSONResponse(content={"status": "failed", "error": str(e)}, status_code=500)


# ============================================================
# OPENAI ENDPOINT / STREAMING
# ============================================================


def fake_stream_generator(content, model_name):
    chat_id = "chatcmpl-browserbridge"
    created_time = int(time.time())
    words = content.split(" ")

    for i, word in enumerate(words):
        chunk = word + (" " if i != len(words) - 1 else "")
        data = {
            "id": chat_id,
            "object": "chat.completion.chunk",
            "created": created_time,
            "model": model_name,
            "choices": [{"index": 0, "delta": {"content": chunk}, "finish_reason": None}],
        }
        yield f"data: {json.dumps(data)}\n\n"

    final_data = {
        "id": chat_id,
        "object": "chat.completion.chunk",
        "created": created_time,
        "model": model_name,
        "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
    }
    yield f"data: {json.dumps(final_data)}\n\n"
    yield "data: [DONE]\n\n"


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    try:
        body = await request.json()
        messages = body.get("messages", [])
        session_id = body.get("session_id", "code")
        account_name = body.get("account", DEFAULT_ACCOUNT)
        provider = body.get("provider", DEFAULT_PROVIDER)

        prompt_parts = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if not content:
                continue
            if isinstance(content, list):
                content = "\n".join(
                    item.get("text", "") if isinstance(item, dict) else item
                    for item in content
                )
            prompt_parts.append(f"[{role.upper()}]\n{content}")

        prompt = "\n\n".join(prompt_parts)
        stream_requested = body.get("stream", False)
        model_name = body.get("model", "openai/browser-model")

        print("\n======================================")
        print(f"REQUEST [account={account_name} session={session_id} provider={provider}]")
        print("======================================\n")

        try:
            reply_text = await registry.run_turn(account_name, session_id, provider, prompt)
        except Exception as e:
            reply_text = f"ERROR: {str(e)}"

        reply_text = clean_text(reply_text) or "ERROR: EMPTY RESPONSE"

        if stream_requested:
            return StreamingResponse(
                fake_stream_generator(reply_text, model_name),
                media_type="text/event-stream",
            )

        response_data = {
            "id": "chatcmpl-browserbridge",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": model_name,
            "choices": [
                {"index": 0, "message": {"role": "assistant", "content": reply_text}, "finish_reason": "stop"}
            ],
            "usage": {
                "prompt_tokens": len(prompt.split()),
                "completion_tokens": len(reply_text.split()),
                "total_tokens": len(prompt.split()) + len(reply_text.split()),
            },
        }
        return JSONResponse(content=response_data)

    except Exception as e:
        error_response = {
            "id": "error",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": "openai/browser-model",
            "choices": [
                {"index": 0, "message": {"role": "assistant", "content": f"ERROR: {str(e)}"}, "finish_reason": "stop"}
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }
        return JSONResponse(content=error_response)


# ============================================================
# STARTUP / SHUTDOWN
#
# No account/Chrome is created eagerly at boot — accounts are created
# lazily on first use (registry.get_account), per the rearchitecture
# requirement that nothing hardcodes which/how-many accounts exist.
# ============================================================


@app.on_event("shutdown")
async def shutdown_event():
    await registry.shutdown_all()


@app.get("/health")
async def health(account: str | None = None, session_id: str = "code"):
    if account is None:
        return {
            "status": "ok",
            "accounts": {
                name: ("alive" if acc._is_alive() else "dead")
                for name, acc in registry.accounts.items()
            },
        }

    try:
        acc = registry.accounts.get(account)
        if not acc or not acc._is_alive():
            return {"status": "dead", "reason": "account_not_running", "account": account}

        session = acc.sessions.get(session_id)
        if not session:
            return {"status": "dead", "reason": "session_not_initialized", "account": account, "session_id": session_id}

        adapter = get_adapter(session.provider)
        ready = await adapter.is_ready(session.page)
        return {
            "status": "ok" if ready else "not_ready",
            "account": account,
            "session_id": session_id,
            "provider": session.provider,
            "url": session.page.url,
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    print("\n======================================")
    print("BROWSER BRIDGE RUNNING")
    print("http://127.0.0.1:8080")
    print("======================================\n")
    uvicorn.run(app, host="127.0.0.1", port=8080)
