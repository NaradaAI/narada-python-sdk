import pytest

from narada import Narada


@pytest.mark.asyncio
async def test_launch_browser():
    narada = Narada()
    session_id = await narada.launch_browser()
    print("Session ID:", session_id)
