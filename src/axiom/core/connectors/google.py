"""Google connector (W3.2): OAuth Device Flow + read-only Gmail/Calendar/Drive."""
from __future__ import annotations

from typing import Any

import httpx

from axiom.core.connectors.base import ConnectorError, ConnectorToken, ConnectorTool
from axiom.core.connectors.device_flow import DeviceFlowClient, DeviceFlowConfig, token_from_payload

GOOGLE_DEVICE_ENDPOINT = "https://oauth2.googleapis.com/device/code"
GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
GOOGLE_REVOCATION_ENDPOINT = "https://oauth2.googleapis.com/revoke"

#: OAuth scopes for the read-only surface plus one mutation scope (drive upload).
SCOPE_CALENDAR_READ = "https://www.googleapis.com/auth/calendar.readonly"
SCOPE_GMAIL_READ = "https://www.googleapis.com/auth/gmail.readonly"
SCOPE_DRIVE_READ = "https://www.googleapis.com/auth/drive.readonly"
SCOPE_DRIVE_FILE = "https://www.googleapis.com/auth/drive.file"


class GoogleConnector:
    """User-authorized Google data via narrow, read-only tools (plus one gated mutation)."""

    id = "google"
    display_name = "Google"

    def __init__(
        self,
        client_id: str,
        client_secret: str | None = None,
        api_key: str | None = None,
        search_engine_id: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        # Custom Search JSON API is keyed (not OAuth), so it is opt-in config.
        self._api_key = api_key
        self._search_engine_id = search_engine_id
        self._flow = DeviceFlowClient(
            DeviceFlowConfig(
                device_endpoint=GOOGLE_DEVICE_ENDPOINT,
                token_endpoint=GOOGLE_TOKEN_ENDPOINT,
                revocation_endpoint=GOOGLE_REVOCATION_ENDPOINT,
                client_id=client_id,
                scopes=self.scopes,
            ),
            transport=transport,
        )
        self._transport = transport

    @property
    def scopes(self) -> tuple[str, ...]:
        return (SCOPE_CALENDAR_READ, SCOPE_GMAIL_READ, SCOPE_DRIVE_READ, SCOPE_DRIVE_FILE)

    def tools(self) -> list[ConnectorTool]:
        return [
            ConnectorTool("search", "Search the web via Google Custom Search (requires an API key)",
                          scopes=(), mutation=False, provider=self.id),
            ConnectorTool("calendar.events", "List upcoming Google Calendar events (read-only)",
                          scopes=(SCOPE_CALENDAR_READ,), mutation=False, provider=self.id),
            ConnectorTool("gmail.messages", "List recent Gmail messages (read-only)",
                          scopes=(SCOPE_GMAIL_READ,), mutation=False, provider=self.id),
            ConnectorTool("drive.files", "List Google Drive files (read-only)",
                          scopes=(SCOPE_DRIVE_READ,), mutation=False, provider=self.id),
            ConnectorTool("drive.upload", "Upload a file to Google Drive (mutates — requires approval)",
                          scopes=(SCOPE_DRIVE_FILE,), mutation=True, provider=self.id),
        ]

    async def begin(self) -> dict[str, Any]:
        authorization = await self._flow.begin()
        return authorization.as_dict()

    async def finish(self, device_code: str) -> ConnectorToken:
        payload = await self._flow.poll(device_code)
        token = token_from_payload(payload, self.scopes)
        if not token.access_token:
            raise ConnectorError("Google returned a token without an access_token")
        return token

    async def revoke(self, token: ConnectorToken) -> bool:
        # Google revokes refresh tokens; access tokens expire on their own.
        if token.refresh_token:
            return await self._flow.revoke(token.refresh_token)
        return await self._flow.revoke(token.access_token)

    async def execute(self, token: ConnectorToken, tool: str, args: dict[str, Any]) -> Any:
        headers = {"Authorization": f"{token.token_type} {token.access_token}"}
        if tool == "search":
            if not self._api_key or not self._search_engine_id:
                raise ConnectorError("Google Search is not configured (api_key + search_engine_id)")
            return await self._get(
                "https://www.googleapis.com/customsearch/v1",
                headers={},
                params={"key": self._api_key, "cx": self._search_engine_id,
                        "q": str(args.get("query") or "")},
            )
        if tool == "calendar.events":
            return await self._get("https://www.googleapis.com/calendar/v3/calendars/primary/events",
                                   headers=headers, params={"maxResults": int(args.get("max", 10))})
        if tool == "gmail.messages":
            return await self._get("https://gmail.googleapis.com/gmail/v1/users/me/messages",
                                   headers=headers, params={"maxResults": int(args.get("max", 10))})
        if tool == "drive.files":
            return await self._get("https://www.googleapis.com/drive/v3/files",
                                   headers=headers, params={"pageSize": int(args.get("max", 10))})
        if tool == "drive.upload":
            metadata = {"name": str(args.get("name") or "upload.txt")}
            return await self._post_multipart(
                "https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart",
                headers=headers, metadata=metadata, content=str(args.get("content") or ""),
            )
        raise ConnectorError(f"unknown tool '{tool}'")

    async def _get(self, url: str, *, headers: dict[str, str], params: dict[str, Any]) -> Any:
        client = httpx.AsyncClient(transport=self._transport, timeout=httpx.Timeout(60.0, connect=15.0))
        try:
            response = await client.get(url, headers=headers, params=params)
        finally:
            await client.aclose()
        if response.status_code != 200:
            raise ConnectorError(f"Google API error: HTTP {response.status_code}")
        return response.json()

    async def _post_multipart(self, url: str, *, headers: dict[str, str], metadata: dict, content: str) -> Any:
        import json

        boundary = "axiom_google_boundary"
        body = (
            f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n"
            f"{json.dumps(metadata)}\r\n"
            f"--{boundary}\r\nContent-Type: text/plain\r\n\r\n"
            f"{content}\r\n"
            f"--{boundary}--"
        )
        client = httpx.AsyncClient(transport=self._transport, timeout=httpx.Timeout(60.0, connect=15.0))
        try:
            response = await client.post(
                url,
                headers={**headers, "Content-Type": f"multipart/related; boundary={boundary}"},
                content=body,
            )
        finally:
            await client.aclose()
        if response.status_code not in (200, 201):
            raise ConnectorError(f"Google upload error: HTTP {response.status_code}")
        return response.json()
