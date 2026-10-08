import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

_AGENTCORE_DOMAIN_PATTERN = re.compile(
    r"(\.)?[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?"
    r"(\.[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?)*"
)
_AGENTCORE_DEFAULT_PROXY_BYPASS_PATTERNS = (".narada.ai",)
# AgentCore Browser's documented proxy credential character sets.
_PROXY_USERNAME_PATTERN = re.compile(r"[a-zA-Z0-9@._+=-]+")
_PROXY_PASSWORD_PATTERN = re.compile(r"[a-zA-Z0-9@._+=\-!#$%*]+")
_MAX_PROXY_CREDENTIAL_LENGTH = 256


def _validate_agentcore_bypass_patterns(bypass: str | None) -> list[str]:
    patterns = [pattern.strip() for pattern in (bypass or "").split(",")]
    patterns = [pattern for pattern in patterns if pattern]
    for pattern in patterns:
        if len(pattern) > 253 or _AGENTCORE_DOMAIN_PATTERN.fullmatch(pattern) is None:
            raise ValueError(
                f"Invalid AgentCore Browser proxy bypass pattern: {pattern!r}"
            )
    effective_patterns = dict.fromkeys(
        (*_AGENTCORE_DEFAULT_PROXY_BYPASS_PATTERNS, *patterns)
    )
    if len(effective_patterns) > 100:
        raise ValueError(
            "AgentCore Browser allows at most 99 custom proxy bypass patterns; "
            "Narada domains are bypassed automatically"
        )
    return patterns


def _default_executable_path() -> str:
    if sys.platform == "win32":
        return "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe"
    elif sys.platform == "darwin":
        return "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    else:
        return "/usr/bin/google-chrome"


def _default_user_data_dir() -> str:
    # Starting from Chrome 136, the default Chrome data directory can no longer be debugged over
    # CDP:
    # - https://developer.chrome.com/blog/remote-debugging-port
    # - https://github.com/browser-use/browser-use/issues/1520
    return str(Path("~/.config/narada/user-data-dirs/default").expanduser())


@dataclass
class ProxyConfig:
    """Configuration for local or AgentCore-managed browser proxies.

    Args:
        server: Proxy server URL. Local browsers support HTTP and SOCKS proxies, for
            example "http://myproxy.com:3128" or "socks5://myproxy.com:3128". Cloud
            browsers support the HTTP proxy endpoints accepted by AgentCore Browser.
        username: Optional username for proxy authentication. Up to 256 letters, digits,
            and ``@ . _ + = -``.
        password: Optional password for proxy authentication. Up to 256 letters, digits,
            and ``@ . _ + = - ! # $ % *``.
        bypass: Optional comma-separated domains to bypass proxy,
                for example ".example.com, chromium.org". Cloud sessions always bypass
                Narada's domains so the extension can reach the Narada API.
        ignore_cert_errors: If True, ignore SSL certificate errors. Required for proxies that
            perform HTTPS inspection (MITM) in local Chrome. Use with caution.
    """

    server: str
    username: str | None = None
    password: str | None = None
    bypass: str | None = None
    ignore_cert_errors: bool = False

    def __post_init__(self) -> None:
        if self.username is not None and (
            len(self.username) > _MAX_PROXY_CREDENTIAL_LENGTH
            or _PROXY_USERNAME_PATTERN.fullmatch(self.username) is None
        ):
            raise ValueError(
                "Proxy username must be 1-256 letters, digits, or @ . _ + = -"
            )
        if self.password is not None and (
            len(self.password) > _MAX_PROXY_CREDENTIAL_LENGTH
            or _PROXY_PASSWORD_PATTERN.fullmatch(self.password) is None
        ):
            raise ValueError(
                "Proxy password must be 1-256 letters, digits, or @ . _ + = - ! # $ % *"
            )

    @property
    def requires_authentication(self) -> bool:
        """Returns True if proxy requires authentication."""
        return self.username is not None and self.password is not None

    def validate(self) -> None:
        """Validates the proxy configuration.

        Raises:
            ValueError: If configuration is invalid.
        """
        if not self.server:
            raise ValueError("Proxy server cannot be empty")

        # Validate that if one credential is provided, both are provided
        if (self.username is None) != (self.password is None):
            raise ValueError(
                "Both username and password must be provided for proxy authentication, "
                "or neither should be provided"
            )

    def _cloud_browser_payload(self) -> dict[str, str]:
        """Return the proxy fields supported by an AgentCore Browser session."""
        self.validate()

        candidate = self.server.strip()
        if "://" not in candidate:
            candidate = f"http://{candidate}"

        try:
            parsed_server = urlsplit(candidate)
            port = parsed_server.port
        except ValueError as error:
            raise ValueError(
                "Proxy server must be a valid HTTP host and port"
            ) from error

        scheme = parsed_server.scheme.lower()
        if scheme == "https":
            raise ValueError(
                "AgentCore Browser proxy settings pass only hostname and port; "
                "they cannot select TLS to the proxy. Use an HTTP proxy endpoint."
            )
        if scheme != "http":
            raise ValueError(
                "AgentCore Browser supports HTTP proxy endpoints only; SOCKS "
                "proxies are supported only by local BrowserEnvironment"
            )
        if (
            not parsed_server.hostname
            or parsed_server.username
            or parsed_server.password
        ):
            raise ValueError(
                "Proxy server must contain a host only; configure credentials "
                "separately"
            )
        if (
            parsed_server.path not in {"", "/"}
            or parsed_server.query
            or parsed_server.fragment
        ):
            raise ValueError("Proxy server must not include a path, query, or fragment")
        if port is not None and not 1 <= port <= 65535:
            raise ValueError("Proxy server port must be between 1 and 65535")
        if self.ignore_cert_errors:
            raise ValueError(
                "ignore_cert_errors is not supported by CloudBrowserEnvironment "
                "proxy settings"
            )
        bypass_patterns = list(
            dict.fromkeys(
                (
                    *_AGENTCORE_DEFAULT_PROXY_BYPASS_PATTERNS,
                    *_validate_agentcore_bypass_patterns(self.bypass),
                )
            )
        )
        payload = {"server": self.server.strip()}
        if self.requires_authentication:
            payload["username"] = self.username or ""
            payload["password"] = self.password or ""
        payload["bypass"] = ",".join(bypass_patterns)
        return payload


@dataclass
class BrowserConfig:
    executable_path: str = field(default_factory=_default_executable_path)
    user_data_dir: str = field(default_factory=_default_user_data_dir)
    profile_directory: str = "Default"
    cdp_host: str = "http://localhost"
    cdp_port: int = 9222
    initialization_url: str = "https://app.narada.ai/initialize"
    extension_id: str = "bhioaidlggjdkheaajakomifblpjmokn"
    interactive: bool = True
    proxy: ProxyConfig | None = None

    @property
    def cdp_url(self) -> str:
        return f"{self.cdp_host}:{self.cdp_port}"
