import asyncio
import json
import re
import time

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse
from playwright.async_api import async_playwright

app = FastAPI()

# ============================================================
# GLOBALS
# ============================================================

browser = None
page = None
playwright_instance = None
lock = asyncio.Lock()

CHATGPT_URL = "https://chatgpt.com/"


# ============================================================
# CLEAN TEXT
# ============================================================


def clean_text(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F]", "", text)
    return text.strip()


# ============================================================
# DYNAMIC WAIT
# ============================================================


async def dynamic_chatgpt_wait(page, max_deadline_ms=600000):
    stop_selector = 'button[data-testid="stop-button"]'
    print("-> Waiting for generation start...")

    try:
        await page.wait_for_selector(stop_selector, state="attached", timeout=5000)
        print("-> Generation started")
    except:
        print("-> Fast response / no stop button")

    print("-> Waiting for generation finish...")

    try:
        await page.wait_for_selector(
            stop_selector, state="hidden", timeout=max_deadline_ms
        )
        print("-> Generation finished")
    except Exception as e:
        print("-> Generation timeout:", e)

    await asyncio.sleep(1)


# ============================================================
# EXTRACT RESPONSE (Pre-Load Memory Hijack)
# ============================================================
# ============================================================
# EXTRACT RESPONSE (Pure Memory Hijack - No Fallbacks)
# ============================================================

async def extract_latest_response(page):
    try:
        last_message = page.locator('[data-message-author-role="assistant"]').last

        # Snapshot all copy buttons ONCE
        buttons = await last_message.locator(
            'button[aria-label="Copy"]'
        ).element_handles()

        print(f"-> Found {len(buttons)} copy button(s)")

        if len(buttons) == 0:
            print("-> No code blocks, returning raw text")
            return clean_text(await last_message.inner_text())

        all_snippets = []

        for btn in buttons:
            await btn.scroll_into_view_if_needed()

            # Clear previous intercepted value
            await page.evaluate("window._interceptedCode = ''")

            # Click the stored button
            await btn.click(force=True)

            # Wait until ChatGPT has written to our hook
            await page.wait_for_function(
                "window._interceptedCode.length > 0",
                timeout=5000,
            )

            code = await page.evaluate("window._interceptedCode")

            if code:
                all_snippets.append(code)

        final_text = "\n\n".join(all_snippets)

        print(f"-> Success: Extracted {len(all_snippets)} pure code block(s)")

        return clean_text(final_text)

    except Exception as e:
        print(f"-> EXTRACTION FAILED: {e}")
        return f"ERROR: {str(e)}"



# ============================================================
# MAIN GPT REQUEST
# ============================================================


async def get_chatgpt_response(prompt: str):
    global page

    async with lock:
        try:
            print("\n======================================")
            print("NEW REQUEST")
            print("======================================\n")

            print("-> Opening fresh chat...")
            await page.goto(CHATGPT_URL)

            prompt_selector = "#prompt-textarea"
            print("-> Waiting for prompt box...")
            await page.wait_for_selector(prompt_selector, timeout=30000)

            print("-> Filling prompt...")
            await page.fill(prompt_selector, prompt)

            print("-> Waiting for send button...")
            send_btn = page.locator('button[data-testid="send-button"]')
            await send_btn.wait_for(state="visible")

            print("-> Clicking send...")
            await send_btn.click()
            print("-> Prompt sent")

            await dynamic_chatgpt_wait(page)

            reply = await extract_latest_response(page)
            reply = clean_text(reply)

            print("\n=========== FINAL RESPONSE ===========\n")
            print(repr(reply[:3000]))
            print("\n======================================\n")

            if not reply:
                return "ERROR: EMPTY RESPONSE"

            return reply

        except Exception as e:
            print("-> MAIN ERROR:", e)
            return f"ERROR: {str(e)}"


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
            "choices": [
                {"index": 0, "delta": {"content": chunk}, "finish_reason": None}
            ],
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
        prompt_parts = []

        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if not content:
                continue

            if isinstance(content, list):
                content = "\n".join(
                    [
                        item.get("text", "") if isinstance(item, dict) else item
                        for item in content
                    ]
                )

            prompt_parts.append(f"[{role.upper()}]\n{content}")

        prompt = "\n\n".join(prompt_parts)
        stream_requested = body.get("stream", False)
        model_name = body.get("model", "openai/browser-model")

        print("\n======================================")
        print("REQUEST FROM AIDER")
        print("======================================\n")

        reply_text = await get_chatgpt_response(prompt)
        reply_text = clean_text(reply_text)

        if not reply_text:
            reply_text = "ERROR: EMPTY RESPONSE"

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
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": reply_text},
                    "finish_reason": "stop",
                }
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
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": f"ERROR: {str(e)}"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }
        return JSONResponse(content=error_response)


# ============================================================
# STARTUP / SHUTDOWN
# ============================================================


async def setup_browser():
    global browser, page, playwright_instance

    print("-> Connecting to Chrome...")
    playwright_instance = await async_playwright().start()
    browser = await playwright_instance.chromium.connect_over_cdp(
        "http://localhost:9222"
    )

    context = browser.contexts[0] if browser.contexts else await browser.new_context()
    page = context.pages[0] if context.pages else await context.new_page()

    # ============================================================
    # THE IRONCLAD HIJACK
    # Overwrite the clipboard API globally before ChatGPT loads
    # ============================================================
    await page.add_init_script("""
        window._interceptedCode = "";

        Object.defineProperty(navigator, 'clipboard', {
            value: {
                writeText: async function(text) {
                    window._interceptedCode = text;
                    return Promise.resolve();
                },
                readText: async function() {
                    return window._interceptedCode;
                }
            },
            writable: true,
            configurable: true
        });
    """)

    print("-> Navigating to ChatGPT...")
    await page.goto(
        "https://chatgpt.com/", wait_until="domcontentloaded", timeout=30000
    )
    print("-> ChatGPT loaded")
    print("-> Browser ready")


@app.on_event("startup")
async def startup_event():
    await setup_browser()


@app.on_event("shutdown")
async def shutdown_event():
    global browser, playwright_instance
    try:
        await browser.disconnect()
    except:
        pass
    try:
        await playwright_instance.stop()
    except:
        pass


@app.get("/health")
async def health():
    try:
        global page
        if not page:
            return {"status": "dead", "reason": "page_not_initialized"}
        if "chatgpt.com" not in page.url:
            return {"status": "dead", "reason": f"wrong_url: {page.url}"}
        await page.wait_for_selector("#prompt-textarea", timeout=10000)
        return {"status": "ok", "chatgpt": "ready", "url": page.url}
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
