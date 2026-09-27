"""Cleanup for one-shot shell commands owned by the agent runtime."""
from __future__ import annotations

import asyncio
import os
import shlex
import shutil
import signal
import subprocess
from pathlib import Path


def process_group_options() -> dict:
    if os.name == "nt":
        # Child processes use redirected stdio and must never create or attach
        # to a console window. Tree cleanup uses taskkill /T, so no process
        # group or detached-process flags are needed.
        return {"creationflags": subprocess.CREATE_NO_WINDOW}
    return {"start_new_session": True}


def command_argv(command: str) -> list[str]:
    """Parse a simple command line without invoking a platform shell.

    Windows shell operators/builtins are intentionally rejected: invoking
    them would require cmd.exe /C. npm/npx .cmd shims are mapped to npm's JS
    CLI and Node so package scripts still start via direct executables.
    """
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        shell_meta = ("|", "&", ">", "<", "\n", "\r")
        if any(char in command for char in shell_meta):
            raise ValueError("shell operators are not supported; execute a program directly")
        argc = ctypes.c_int()
        parse = ctypes.windll.shell32.CommandLineToArgvW
        parse.argtypes = (wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_int))
        parse.restype = ctypes.POINTER(wintypes.LPWSTR)
        argv_ptr = parse(command, ctypes.byref(argc))
        if not argv_ptr:
            raise ValueError("invalid command line")
        try:
            argv = [argv_ptr[i] for i in range(argc.value)]
        finally:
            ctypes.windll.kernel32.LocalFree(argv_ptr)
    else:
        argv = shlex.split(command)
    if not argv:
        raise ValueError("command is empty")
    return direct_executable_argv(argv)


def direct_executable_argv(argv: list[str]) -> list[str]:
    """Normalize a pre-tokenized command to direct executables on Windows."""
    if not argv:
        raise ValueError("command is empty")
    if os.name != "nt":
        return argv
    executable = Path(argv[0])
    if executable.name.lower() in {"cmd", "cmd.exe", "command.com"}:
        raise ValueError("cmd.exe is not used for direct command execution")
    if executable.suffix.lower() in {".cmd", ".bat"}:
        stem = executable.stem.lower()
        if stem in {"npm", "npx"}:
            node = shutil.which("node.exe") or shutil.which("node")
            if node:
                npm_cli = Path(node).resolve().parent / "node_modules" / "npm" / "bin" / (
                    "npx-cli.js" if stem == "npx" else "npm-cli.js"
                )
                if npm_cli.is_file():
                    return [node, str(npm_cli), *argv[1:]]
        raise ValueError("batch files are not launched through cmd.exe")
    if argv[0].lower() in {"npm", "npx"}:
        node = shutil.which("node.exe") or shutil.which("node")
        if node:
            npm_cli = Path(node).resolve().parent / "node_modules" / "npm" / "bin" / (
                "npx-cli.js" if argv[0].lower() == "npx" else "npm-cli.js"
            )
            if npm_cli.is_file():
                return [node, str(npm_cli), *argv[1:]]
        raise FileNotFoundError("Node.js npm CLI was not found")
    return argv


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
            **process_group_options(),
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
