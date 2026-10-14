import asyncio
import sys
from collections.abc import Callable


def pytest_asyncio_loop_factories() -> dict[str, Callable[[], asyncio.AbstractEventLoop]]:
    # curl requires add_reader(), which the Windows default Proactor loop lacks.
    # Keep warnings as errors and exercise the real transport with a supported loop.
    factory = asyncio.SelectorEventLoop if sys.platform == "win32" else asyncio.new_event_loop
    return {"safehttp": factory}
