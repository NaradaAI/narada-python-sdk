from typing import Never


def assert_never() -> Never:
    raise AssertionError("Expected code to be unreachable")
