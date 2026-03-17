"""AI execution — Claude CLI primary, Ollama fallback."""
import asyncio
import json as _json
import logging
import os
import time
from typing import Callable, Awaitable

import httpx

from ..config import settings

logger = logging.getLogger("seaclip.ai")

# Inherit system environment so Claude CLI gets PATH, API keys, etc.
_env = os.environ.copy()

# Type for the optional log callback
LogCallback = Callable[[str], Awaitable[None]] | None


def _summarise_event(evt: dict) -> str | None:
    """Extract a short human-readable line from a stream-json event."""
    etype = evt.get("type", "")

    if etype == "tool_use":
        tool = evt.get("tool", "unknown")
        inp = evt.get("input", {})
        if isinstance(inp, dict):
            detail = inp.get("command") or inp.get("file_path") or inp.get("pattern") or ""
            if len(detail) > 120:
                detail = detail[:117] + "..."
            return f"⚙ {tool}: {detail}" if detail else f"⚙ {tool}"
        return f"⚙ {tool}"

    if etype == "tool_result":
        tool = evt.get("tool", "")
        output = evt.get("output", "")
        lines = output.count("\n") + 1 if output else 0
        chars = len(output)
        return f"  ↳ {tool} returned ({chars} chars, {lines} lines)"

    if etype == "assistant":
        sub = evt.get("subtype", "")
        text = evt.get("text", "")
        if sub == "thinking":
            snippet = text[:80].replace("\n", " ")
            return f"💭 {snippet}..." if len(text) > 80 else f"💭 {snippet}"
        if text.strip():
            first = text.strip().split("\n")[0][:100]
            return f"📝 {first}"

    if etype == "system":
        msg = evt.get("message", "")
        if msg:
            return f"⚡ {msg[:120]}"

    if etype == "result":
        return "✓ Agent produced final output"

    return None


async def claude_chat(prompt: str, timeout: int = 600, on_log: LogCallback = None) -> str:
    """Call Claude Code CLI as subprocess, streaming stdout as JSON events."""
    proc = await asyncio.create_subprocess_exec(
        settings.claude_bin,
        "-p",
        "--verbose",
        "--model", settings.claude_model,
        "--output-format", "stream-json",
        "--dangerously-skip-permissions",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=_env,
    )

    # Send prompt to stdin and close it
    proc.stdin.write(prompt.encode())
    await proc.stdin.drain()
    proc.stdin.close()

    # Collect full output text from assistant messages
    result_text_parts: list[str] = []
    stderr_lines: list[str] = []
    last_event_time = time.monotonic()

    async def _read_stdout():
        nonlocal last_event_time
        while True:
            line = await proc.stdout.readline()
            if not line:
                break
            text = line.decode().strip()
            if not text:
                continue

            try:
                evt = _json.loads(text)
            except _json.JSONDecodeError:
                continue

            last_event_time = time.monotonic()

            # Collect final text from result or assistant text events
            etype = evt.get("type", "")
            if etype == "result":
                result_text_parts.append(evt.get("result", ""))
            elif etype == "assistant" and evt.get("subtype") == "text":
                result_text_parts.append(evt.get("text", ""))

            # Stream summary to live feed
            if on_log:
                summary = _summarise_event(evt)
                if summary:
                    try:
                        await on_log(summary)
                    except Exception:
                        pass

    async def _read_stderr():
        while True:
            line = await proc.stderr.readline()
            if not line:
                break
            text = line.decode().strip()
            if text:
                stderr_lines.append(text)
                if on_log:
                    try:
                        await on_log(f"stderr: {text[:150]}")
                    except Exception:
                        pass

    async def _heartbeat():
        """Send periodic status if no events for a while."""
        nonlocal last_event_time
        while True:
            await asyncio.sleep(8)
            if proc.returncode is not None:
                break
            elapsed = time.monotonic() - last_event_time
            if elapsed > 8 and on_log:
                try:
                    await on_log(f"⏳ Processing... ({int(elapsed)}s since last event)")
                except Exception:
                    pass

    try:
        await asyncio.wait_for(
            asyncio.gather(
                _read_stdout(),
                _read_stderr(),
                _heartbeat(),
            ),
            timeout=timeout,
        )
        await proc.wait()
    except asyncio.TimeoutError:
        proc.kill()
        raise TimeoutError(f"Claude CLI timed out after {timeout}s")

    if proc.returncode != 0:
        err_msg = "\n".join(stderr_lines[-5:]) if stderr_lines else "unknown error"
        raise RuntimeError(f"Claude CLI failed (rc={proc.returncode}): {err_msg}")

    output = "".join(result_text_parts).strip()
    if not output:
        err_output = "\n".join(stderr_lines) if stderr_lines else ""
        if err_output:
            logger.info("Claude CLI stdout empty, using stderr (%d chars)", len(err_output))
            return err_output
        logger.info("Claude CLI completed with empty stdout — agent likely used tools directly")
        return "(Agent completed work via tool execution — see GitHub for details)"
    return output


async def ollama_chat(system_prompt: str, messages: list[dict]) -> str:
    """Ollama fallback via HTTP API."""
    ollama_messages = [{"role": "system", "content": system_prompt}] + messages
    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.post(
            f"{settings.ollama_base_url}/api/chat",
            json={"model": settings.ollama_model, "messages": ollama_messages, "stream": False},
        )
        if r.status_code != 200:
            raise RuntimeError(f"Ollama returned {r.status_code}")
        return r.json().get("message", {}).get("content", "No response generated.")


async def ollama_generate(prompt: str, timeout: int = 300) -> str:
    """Ollama single-prompt generation (for agent pipelines)."""
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.post(
            f"{settings.ollama_base_url}/api/generate",
            json={"model": settings.ollama_model, "prompt": prompt, "stream": False},
        )
        if r.status_code != 200:
            raise RuntimeError(f"Ollama returned {r.status_code}")
        return r.json().get("response", "No response generated.")


async def chat(system_prompt: str, messages: list[dict]) -> str:
    """Primary entry — Claude first, Ollama fallback."""
    conversation = "\n\n".join(
        f"{'User' if m['role'] == 'user' else 'Assistant'}: {m['content']}"
        for m in messages
    )
    full_prompt = f"{system_prompt}\n\nConversation:\n{conversation}\n\nRespond concisely."

    try:
        return await claude_chat(full_prompt)
    except Exception as e:
        logger.warning("Claude CLI failed (%s), falling back to Ollama", e)
        return await ollama_chat(system_prompt, messages)
