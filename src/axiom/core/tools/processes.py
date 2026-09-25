"""Cleanup for one-shot shell commands owned by the agent runtime."""
from __future__ import annotations

import asyncio
import os
import signal
import subprocess


def process_group_options() -> dict:
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


async def terminate_process_tree(proc: asyncio.subprocess.Process) -> None:
    """Terminate the shell and its children, then drain/reap the shell.

    POSIX callers must spawn with start_new_session; Windows uses taskkill /T.
    This is runtime cleanup, not a model-facing shell command.
    """
    if os.name == "nt" and proc.returncode is None:
        killer = await asyncio.create_subprocess_exec(
            "taskkill", "/PID", str(proc.pid), "/T", "/F",
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            await asyncio.wait_for(killer.wait(), timeout=10)
        except TimeoutError:
            killer.kill()
            await killer.wait()
    elif os.name != "nt":
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    if proc.returncode is None:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
    await asyncio.wait_for(proc.communicate(), timeout=10)
