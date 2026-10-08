import pytest
from narada.config import ProxyConfig, _validate_agentcore_bypass_patterns


def test_cloud_browser_proxy_payload_always_bypasses_narada_domains() -> None:
    config = ProxyConfig(server="proxy.example.com:8080")

    assert config._cloud_browser_payload() == {
        "server": "proxy.example.com:8080",
        "bypass": ".narada.ai",
    }


def test_cloud_browser_proxy_payload_deduplicates_narada_bypass_pattern() -> None:
    config = ProxyConfig(
        server="proxy.example.com:8080",
        bypass=".example.com, .narada.ai",
    )

    assert config._cloud_browser_payload()["bypass"] == ".narada.ai,.example.com"


def test_agentcore_bypass_validation_reserves_slot_for_narada_domains() -> None:
    bypass = ",".join(f"example{index}.com" for index in range(100))

    with pytest.raises(ValueError, match="99 custom proxy bypass patterns"):
        _validate_agentcore_bypass_patterns(bypass)
