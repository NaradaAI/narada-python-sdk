from __future__ import annotations

import logging
import os
from typing import Any

import semver
from narada.version import __version__
from narada_core.models import _SdkConfig
from pyodide.http import pyfetch


class Narada:
    def __init__(self, *, api_key: str | None = None) -> None:
        self._api_key = api_key or os.environ["NARADA_API_KEY"]

    async def __aenter__(self) -> Narada:
        await self._validate_sdk_config()
        return self

    async def __aexit__(self, *args: Any) -> None:
        pass

    async def _fetch_sdk_config(self) -> _SdkConfig | None:
        base_url = os.getenv("NARADA_API_BASE_URL", "https://api.narada.ai/fast/v2")
        url = f"{base_url}/sdk/config"

        try:
            resp = await pyfetch(url, headers={"x-api-key": self._api_key})
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
        if semver.compare(__version__, package_config.min_required_version) < 0:
            raise RuntimeError(
                f"narada-pyodide<={__version__} is not supported. Please reload the page to "
                f"upgrade to version {package_config.min_required_version} or higher."
            )
