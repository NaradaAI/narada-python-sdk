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
class BrowserConfig:
    executable_path: str = field(default_factory=_default_executable_path)
    user_data_dir: str = field(default_factory=_default_user_data_dir)
    profile_directory: str = "Default"
    cdp_port: int = 9222
    initialization_url: str = "https://app.narada.ai/initialize"
    extension_id: str = "bhioaidlggjdkheaajakomifblpjmokn"
    interactive: bool = True
