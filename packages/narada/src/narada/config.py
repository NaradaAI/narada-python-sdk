import sys
from dataclasses import dataclass, field
from pathlib import Path


def _default_executable_path() -> str:
    if sys.platform == "win32":
        return "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe"
    elif sys.platform == "darwin":
        return "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    else:
        raise NotImplementedError(
            f"No default browser executable path for {sys.platform}"
        )


def _default_user_data_dir() -> str:
    # Starting from Chrome 136, the default Chrome data directory can no longer be debugged over
    # CDP:
    # - https://developer.chrome.com/blog/remote-debugging-port
    # - https://github.com/browser-use/browser-use/issues/1520
    return str(Path("~/.config/narada/user-data-dirs/default").expanduser())


@dataclass
class ProxyConfig:
    """Configuration for HTTP/HTTPS/SOCKS5 proxy.

    Args:
        server: Proxy server URL. HTTP and SOCKS proxies are supported, for example
                "http://myproxy.com:3128" or "socks5://myproxy.com:3128".
                Short form "myproxy.com:3128" is considered an HTTP proxy.
        username: Optional username for proxy authentication.
        password: Optional password for proxy authentication.
        bypass: Optional comma-separated domains to bypass proxy,
                for example ".com, chromium.org, .domain.com".
        ignore_cert_errors: If True, ignore SSL certificate errors. Required for proxies that
                            perform HTTPS inspection (MITM). Use with caution.
    """

    server: str
    username: str | None = None
    password: str | None = None
    bypass: str | None = None
    ignore_cert_errors: bool = False

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
