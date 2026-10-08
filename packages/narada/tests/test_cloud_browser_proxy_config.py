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


def test_cloud_browser_proxy_payload_forwards_credentials_for_backend_storage() -> None:
    config = ProxyConfig(
        server="proxy.example.com:8080",
        username="proxy-user",
        password="proxy-password",
    )

    assert config._cloud_browser_payload() == {
        "server": "proxy.example.com:8080",
        "username": "proxy-user",
        "password": "proxy-password",
        "bypass": ".narada.ai",
    }


def test_proxy_config_accepts_agentcore_credential_characters() -> None:
    config = ProxyConfig(
        server="proxy.example.com:8080",
        username="brd-customer_1@example.com+zone=us",
        password="p@ss.w_r+d=-!#$%*",
    )

    assert config.requires_authentication


@pytest.mark.parametrize(
    ("username", "password", "message"),
    [
        ("proxy user", "password", "username"),
        ("proxy:user", "password", "username"),
        ("", "password", "username"),
        ("u" * 257, "password", "username"),
        ("proxy-user", "pass word", "password"),
        ("proxy-user", "pass&word", "password"),
        ("proxy-user", "line\nbreak", "password"),
        ("proxy-user", "p" * 257, "password"),
    ],
)
def test_proxy_config_rejects_unsupported_credential_characters(
    username: str, password: str, message: str
) -> None:
    with pytest.raises(ValueError, match=f"Proxy {message} must be") as error:
        ProxyConfig(
            server="proxy.example.com:8080",
            username=username,
            password=password,
        )

    assert password not in str(error.value)


def test_cloud_browser_proxy_payload_rejects_only_one_credential() -> None:
    config = ProxyConfig(server="proxy.example.com:8080", username="proxy-user")

    with pytest.raises(ValueError, match="Both username and password"):
        config._cloud_browser_payload()


def test_agentcore_bypass_validation_reserves_slot_for_narada_domains() -> None:
    bypass = ",".join(f"example{index}.com" for index in range(100))

    with pytest.raises(ValueError, match="99 custom proxy bypass patterns"):
        _validate_agentcore_bypass_patterns(bypass)
