"""OS-protected secret storage (release-security audit, P0).

Provider API keys must never rest as plaintext on disk. This module is the
single place where key material crosses the disk boundary:

- Windows: DPAPI, user scope, via ``ctypes`` (no new dependencies). Only the
  same Windows user can decrypt the blob.
- Other platforms: no OS keystore is used on purpose (dependency-free core);
  values are stored as-is and the file itself is restricted to ``0o600``.
  This is documented, not obfuscated — see :func:`protect`.

``ProviderManager`` protects on :meth:`save` and unprotects on load, so the
in-memory ``ProviderConfig.api_key`` stays working plaintext while
``providers.json`` only ever holds opaque blobs. Legacy plaintext entries
migrate transparently: they load as-is and are rewritten protected on the
next save (``set_key`` / ``test_provider`` both save).

Error messages here never include key material.
"""

from __future__ import annotations

import base64
import binascii
import os
import sys
from pathlib import Path


class SecretsError(Exception):
    """Protection or recovery of a stored secret failed (message has no secret)."""


#: Stored-value marker for DPAPI blobs. Anything without this prefix is treated
#: as a legacy plaintext entry (or empty) and returned as-is by ``unprotect``.
DPAPI_PREFIX = "$dpapi1$"


def is_protected(stored: str) -> bool:
    """Whether ``stored`` is an opaque protected blob (not plaintext)."""
    return stored.startswith(DPAPI_PREFIX)


def protect(value: str) -> str:
    """Protect ``value`` for disk storage; ``""`` stays ``""``.

    Raises :class:`SecretsError` when the OS protection itself fails — callers
    must fail closed (never fall back to writing plaintext silently).
    """
    if not value:
        return ""
    if sys.platform == "win32":
        return DPAPI_PREFIX + base64.b64encode(_dpapi_protect(value)).decode("ascii")
    # POSIX: transparent passthrough; `secure_file` restricts the file to 0600.
    return value


def unprotect(stored: str) -> str:
    """Recover working plaintext from a stored value.

    Legacy plaintext (or ``""``) passes through so old ``providers.json``
    files keep working until they are rewritten protected. Corrupt blobs
    raise :class:`SecretsError` — the caller treats the key as missing and
    the user re-enters it.
    """
    if not stored or not stored.startswith(DPAPI_PREFIX):
        return stored
    try:
        raw = base64.b64decode(stored[len(DPAPI_PREFIX) :], validate=True)
    except (binascii.Error, ValueError) as exc:
        raise SecretsError("stored secret is not valid base64") from exc
    return _dpapi_unprotect(raw)


def secure_file(path: Path) -> None:
    """Best-effort ``0o600`` on the secrets file (POSIX real, Windows harmless).

    On Windows the DPAPI blob is already user-bound, so ACL tightening is a
    bonus, not the protection — a failed chmod never blocks the save.
    """
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _dpapi_protect(value: str) -> bytes:
    import ctypes
    from ctypes import wintypes

    crypt32 = ctypes.WinDLL("crypt32.dll")
    kernel32 = ctypes.WinDLL("kernel32.dll")

    class DataBlob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]

    plain = value.encode("utf-8")
    # NOTE: the buffer must stay alive across the call — keep it referenced.
    plain_buf = ctypes.create_string_buffer(plain)
    blob_in = DataBlob(len(plain), ctypes.cast(plain_buf, ctypes.POINTER(ctypes.c_byte)))
    out = DataBlob()
    # CRYPTPROTECT_UI_FORBIDDEN: never prompt; user scope is the default.
    ok = crypt32.CryptProtectData(ctypes.byref(blob_in), None, None, None, None, 0x01, ctypes.byref(out))
    if not ok:
        raise SecretsError("DPAPI protect failed")
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        kernel32.LocalFree(out.pbData)


def _dpapi_unprotect(raw: bytes) -> str:
    import ctypes
    from ctypes import wintypes

    crypt32 = ctypes.WinDLL("crypt32.dll")
    kernel32 = ctypes.WinDLL("kernel32.dll")

    class DataBlob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]

    buf = ctypes.create_string_buffer(raw)
    blob_in = DataBlob(len(raw), ctypes.cast(buf, ctypes.POINTER(ctypes.c_byte)))
    out = DataBlob()
    ok = crypt32.CryptUnprotectData(ctypes.byref(blob_in), None, None, None, None, 0x01, ctypes.byref(out))
    if not ok:
        raise SecretsError("DPAPI unprotect failed (wrong user or corrupt blob)")
    try:
        return ctypes.string_at(out.pbData, out.cbData).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SecretsError("stored secret is not valid text") from exc
    finally:
        kernel32.LocalFree(out.pbData)


__all__ = ["DPAPI_PREFIX", "SecretsError", "is_protected", "protect", "secure_file", "unprotect"]
