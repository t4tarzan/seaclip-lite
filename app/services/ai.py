"""AI execution — Claude CLI primary, Ollama fallback."""
import asyncio
import logging

import httpx

from ..config import settings

logger = logging.getLogger("seaclip.ai")


async def claude_chat(prompt: str) -> str:
    """Call Claude Code CLI as subprocess."""
    proc = await asyncio.create_subprocess_exec(
        settings.claude_bin,
        "-p",
        "--model", settings.claude_model,
        "--output-format", "text",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=None,
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(input=prompt.encode()),
            timeout=120,
        )
    except asyncio.TimeoutError:
        proc.kill()
        raise TimeoutError("Claude CLI timed out after 120s")

    if proc.returncode != 0:
        err_msg = stderr.decode().strip() if stderr else "unknown error"
        raise RuntimeError(f"Claude CLI failed (rc={proc.returncode}): {err_msg}")

    output = stdout.decode().strip()
    if not output:
        raise RuntimeError("Claude returned empty response")
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


async def chat(system_prompt: str, messages: list[dict]) -> str:
    """Primary entry — Claude first, Ollama fallback."""
    # Build a single prompt for Claude CLI
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
