"""Partial direct Rust API-key foundation; existing OpenMates stays supported."""
from __future__ import annotations
import asyncio
from collections.abc import Awaitable, Callable
import json
from typing import Any

class RustApiKeyClientError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code

def _failure(error: Exception) -> RustApiKeyClientError:
    if isinstance(error, RustApiKeyClientError):
        return error
    try:
        value = json.loads(str(error))
        if isinstance(value, dict) and isinstance(value.get("code"), str) and isinstance(value.get("message"), str):
            return RustApiKeyClientError(value["code"], value["message"])
    except (ValueError, TypeError):
        pass
    return RustApiKeyClientError("native_failure", "The native API-key operation failed.")

class RustApiKeyClient:
    def __init__(self, *, api_key: str, api_url: str, device_id: str,
                 enhanced_privacy: bool, allow_private_operations: bool,
                 app_url: str | None = None):
        if not isinstance(api_key, str) or not api_key or not isinstance(api_url, str) or not isinstance(device_id, str) or not isinstance(enhanced_privacy, bool) or not isinstance(allow_private_operations, bool):
            raise RustApiKeyClientError("invalid_argument", "Supply explicit API-key credentials, endpoint, device identity and policy.")
        try:
            from ._native import NativeApiKeyClient
        except ImportError:
            raise RustApiKeyClientError("native_binding_unavailable", "Install an OpenMates build containing the native API-key extension for this platform.") from None
        try:
            self._native = NativeApiKeyClient(json.dumps({"api_key": api_key, "api_url": api_url, "device_id": device_id, "app_url": app_url, "enhanced_privacy": enhanced_privacy, "allow_private_operations": allow_private_operations}))
        except Exception as error:
            raise _failure(error) from None
        self._inflight: set[asyncio.Task[Any]] = set()

    async def _invoke(self, operation: Callable[[Any], Awaitable[Any]]) -> Any:
        try:
            request = self._native.request()
        except Exception as error:
            raise _failure(error) from None
        abandoned = [False]
        async def drive():
            # The real native callable is scheduled after original sync admission.
            return await operation(request)
        task = asyncio.create_task(drive())
        self._inflight.add(task)
        def settled(done):
            self._inflight.discard(done)
            if abandoned[0]:
                try:
                    done.result().discard()
                except BaseException:
                    pass
                request.cancel()
        task.add_done_callback(settled)
        output = None
        try:
            output = await asyncio.shield(task)
            return json.loads(output.release_json())
        except asyncio.CancelledError:
            abandoned[0] = True
            request.cancel()
            # Shield actual Rust completion; repeated host cancellation leaves a
            # retained task/callback to discard only A once that driver settles.
            try:
                output = await asyncio.shield(task)
            except BaseException:
                pass
            raise
        except Exception as error:
            raise _failure(error) from None
        finally:
            if output is not None:
                output.discard()
            request.cancel()

    async def account_info(self) -> dict[str, Any]:
        return await self._invoke(lambda request: request.account_info_prepare())

    async def run_skill(self, app: str, skill: str, input: dict[str, Any]) -> Any:
        return await self._invoke(lambda request: request.run_skill_prepare(app, skill, json.dumps(input, ensure_ascii=False, allow_nan=False)))

    async def list_project_sources_raw(self, project: str, *, filters: dict[str, Any]) -> list[Any]:
        """Raw source rows; no Master-key, Project resolution or CLI profile."""
        return await self._invoke(lambda request: request.list_project_sources_raw_prepare(project, json.dumps(filters, ensure_ascii=False, allow_nan=False)))

    def cancel(self) -> None:
        try:
            self._native.cancel()
        except Exception as error:
            raise _failure(error) from None

    def close(self) -> None:
        try:
            self._native.close()
        except Exception as error:
            raise _failure(error) from None
