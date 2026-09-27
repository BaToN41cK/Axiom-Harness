"""MCP-совместимый слой (п.15): клиенты внешних MCP-серверов.

Минимальный JSON-RPC 2.0 поверх stdio: initialize, tools/list, tools/call.
Без переписывания Core: MCP-тулы регистрируются в ToolRegistry как обычные.
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field

from axiom.core.tools.base import ToolDefinition, ToolPermission, ToolResult
from axiom.core.tools.processes import (
    direct_executable_argv,
    process_group_options,
    terminate_process_tree,
)


@dataclass
class MCPServer:
    name: str
    command: list[str] = field(default_factory=list)
    tools: list[ToolDefinition] = field(default_factory=list)


class MCPClient:
    """Один MCP-сервер (stdio JSON-RPC). Best-effort: ошибки -> ToolResult."""

    def __init__(self, server: MCPServer, *, timeout: float = 20.0) -> None:
        self.server = server
        self.timeout = timeout
        self._id = 0

    def _next_id(self) -> int:
        self._id += 1
        return self._id

    async def _rpc(self, method: str, params: dict | None = None) -> dict:
        if not self.server.command:
            raise RuntimeError(f"MCP server '{self.server.name}' has no command")
        proc = await asyncio.create_subprocess_exec(
            *direct_executable_argv(self.server.command), stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            **process_group_options())
        request = {"jsonrpc": "2.0", "id": self._next_id(), "method": method,
                   "params": params or {}}
        try:
            assert proc.stdin is not None and proc.stdout is not None
            proc.stdin.write((json.dumps(request) + "\n").encode("utf-8"))
            await proc.stdin.drain()
            proc.stdin.close()
            raw = await asyncio.wait_for(proc.stdout.readline(), timeout=self.timeout)
            try:
                return json.loads(raw.decode("utf-8") or "{}")
            except Exception:
                return {}
        finally:
            if proc.returncode is None:
                await terminate_process_tree(proc)

    async def list_tools(self) -> list[ToolDefinition]:
        try:
            response = await self._rpc("tools/list")
            result = response.get("result", {}) if isinstance(response, dict) else {}
            items = result.get("tools", []) if isinstance(result, dict) else []
            out: list[ToolDefinition] = []
            for item in items:
                if not isinstance(item, dict) or not item.get("name"):
                    continue
                out.append(ToolDefinition(
                    name=f"mcp_{self.server.name}_{item['name']}",
                    description=str(item.get("description") or f"MCP {item['name']}"),
                    parameters=item.get("inputSchema") or {},
                    permission=ToolPermission.ASK))
            self.server.tools = out
            return out
        except Exception:
            return []

    async def call_tool(self, tool: str, arguments: dict | None = None) -> ToolResult:
        short = tool[len(f"mcp_{self.server.name}_"):] if tool.startswith(f"mcp_{self.server.name}_") else tool
        try:
            response = await self._rpc("tools/call",
                                       {"name": short, "arguments": arguments or {}})
            if isinstance(response, dict) and response.get("error"):
                return ToolResult(name=tool, ok=False, error=str(response["error"])[:1000])
            result = response.get("result", {}) if isinstance(response, dict) else {}
            content = result.get("content") if isinstance(result, dict) else None
            if isinstance(content, list):
                text = "\n".join(str(c.get("text", c)) if isinstance(c, dict) else str(c)
                                 for c in content)[:6000]
            else:
                text = json.dumps(result, ensure_ascii=False)[:6000]
            return ToolResult(name=tool, ok=True, content=text or "(empty MCP result)")
        except Exception as exc:
            return ToolResult(name=tool, ok=False, error=f"{type(exc).__name__}: {exc}")


class MCPManager:
    """Реестр MCP-серверов + регистрация их тулов в ToolRegistry."""

    def __init__(self) -> None:
        self._servers: dict[str, MCPClient] = {}

    def add_server(self, name: str, command: list[str]) -> MCPClient:
        client = MCPClient(MCPServer(name=name, command=list(command)))
        self._servers[name] = client
        return client

    def remove_server(self, name: str) -> bool:
        return self._servers.pop(name, None) is not None

    def servers(self) -> list[str]:
        return list(self._servers)

    async def register_all(self, registry) -> list[str]:
        names: list[str] = []
        for client in self._servers.values():
            for definition in await client.list_tools():
                async def _handler(_c: MCPClient = client, _n: str = definition.name,
                                   **kwargs) -> ToolResult:
                    return await _c.call_tool(_n, kwargs)

                registry.register(definition, _handler)
                names.append(definition.name)
        return names
