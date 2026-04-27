from __future__ import annotations

import json
import logging
import os
from typing import Any

from narada_core.models import _SdkConfig
from packaging.version import Version
from pyodide.http import pyfetch

from narada.version import __version__
from narada.window import CloudBrowserWindow, _build_auth_headers, _normalize_narada_env


class Narada:
    def __init__(self, *, api_key: str | None = None) -> None:
        self._api_key = api_key or os.environ.get("NARADA_API_KEY")
        self._user_id = os.environ.get("NARADA_USER_ID")
        self._env = _normalize_narada_env(os.environ.get("NARADA_ENV"))

        if self._api_key is None and (self._user_id is None or self._env is None):
            raise ValueError(
                "Either `api_key` or all of `NARADA_USER_ID` and `NARADA_ENV` must be provided"
            )

    async def __aenter__(self) -> Narada:
        await self._validate_sdk_config()
        return self

    async def __aexit__(self, *args: Any) -> None:
        pass

    async def _fetch_sdk_config(self) -> _SdkConfig | None:
        base_url = os.getenv("NARADA_API_BASE_URL", "https://api.narada.ai/fast/v2")
        url = f"{base_url}/sdk/config"
        headers = await _build_auth_headers(
            api_key=self._api_key,
            user_id=self._user_id,
            env=self._env,
        )

        try:
            resp = await pyfetch(url, headers=headers)
            if not resp.ok:
                logging.warning(
                    "Failed to fetch SDK config: %s %s", resp.status, await resp.text()
                )
                return None

            return _SdkConfig.model_validate(await resp.json())
        except Exception as e:
            logging.warning("Failed to fetch SDK config: %s", e)
            return None

    async def _validate_sdk_config(self) -> None:
        config = await self._fetch_sdk_config()
        if config is None:
            return

        package_config = config.packages["narada-pyodide"]
        current_version = Version(__version__)
        min_required_version = Version(package_config.min_required_version)
        if current_version < min_required_version:
            raise RuntimeError(
                f"narada-pyodide<={__version__} is not supported. Please reload the page to "
                f"upgrade to version {package_config.min_required_version} or higher."
            )

    async def open_and_initialize_cloud_browser_window(
        self,
        *,
        session_name: str | None = None,
        session_timeout: int | None = None,
        require_extension: bool = True,
    ) -> CloudBrowserWindow:
        base_url = os.getenv("NARADA_API_BASE_URL", "https://api.narada.ai/fast/v2")
        endpoint_url = (
            f"{base_url}/cloud-browser/create-and-initialize-cloud-browser-session"
        )
        headers = await _build_auth_headers(
            api_key=self._api_key,
            user_id=self._user_id,
            env=self._env,
        )
        request_body = {
            "session_name": session_name,
            "session_timeout": session_timeout,
            "require_extension": require_extension,
        }

        resp = await pyfetch(
            endpoint_url,
            method="POST",
            headers=headers,
            body=json.dumps(request_body),
        )
        if not resp.ok:
            raise RuntimeError(
                "Failed to create and initialize cloud browser session: "
                f"{resp.status} {await resp.text()}\n"
                f"Endpoint URL: {endpoint_url}"
            )

        response_data = await resp.json()
        return CloudBrowserWindow(
            browser_window_id=response_data["browser_window_id"],
            session_id=response_data["session_id"],
            api_key=self._api_key,
            user_id=self._user_id,
            env=self._env,
        )
