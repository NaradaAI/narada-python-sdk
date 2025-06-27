import pytest

from narada import Narada


@pytest.mark.asyncio
async def test_launch_browser():
    narada = Narada()
    session = await narada.launch_browser_and_initialize()
    print("Narada session:", session)
