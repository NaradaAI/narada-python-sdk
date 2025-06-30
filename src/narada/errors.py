class NaradaError(Exception):
    pass


class NaradaTimeoutError(NaradaError):
    pass


class NaradaUnsupportedBrowserError(NaradaError):
    pass


class NaradaExtensionMissingError(NaradaError):
    pass


class NaradaInitializationError(NaradaError):
    pass
