"""Non-blocking stdin reader for mid-execution steering.

Provides SteerReader — a daemon-thread based reader that captures user input
while the agent loop is running, without blocking the async event loop.
"""

import asyncio
import sys
import threading
import time
from collections.abc import Callable


class SteerReader:
    """Reads stdin in a daemon thread and pushes lines to an async queue.

    Usage::

        reader = SteerReader()
        reader.start(queue, asyncio.get_event_loop())
        # ... run agent ...
        reader.stop()
    """

    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def start(self, queue: "asyncio.Queue[str]", loop: asyncio.AbstractEventLoop) -> None:
        """Start the background stdin reader thread."""
        if self._thread is not None:
            return

        self._stop.clear()

        def _put(line: str) -> None:
            loop.call_soon_threadsafe(queue.put_nowait, line)

        if sys.platform == "win32":
            target = _win_reader
        else:
            target = _unix_reader

        self._thread = threading.Thread(
            target=target,
            args=(_put, self._stop),
            daemon=True,
            name="steer-reader",
        )
        self._thread.start()

    def stop(self) -> None:
        """Signal the reader thread to stop."""
        self._stop.set()
        self._thread = None


def _win_reader(put: Callable[[str], None], stop: threading.Event) -> None:
    """Windows non-blocking stdin reader using msvcrt."""
    import msvcrt

    buf: list[str] = []
    while not stop.is_set():
        if msvcrt.kbhit():
            ch = msvcrt.getwch()
            if ch in ("\r", "\n"):
                line = "".join(buf).strip()
                buf.clear()
                sys.stdout.write("\n")
                sys.stdout.flush()
                if line:
                    put(line)
            elif ch == "\x08":  # Backspace
                if buf:
                    buf.pop()
                    sys.stdout.write("\x08 \x08")
                    sys.stdout.flush()
            elif ch == "\x03":  # Ctrl+C
                break
            elif ch == "\x00" or ch == "\xe0":
                # Skip special keys (arrows, function keys)
                msvcrt.getwch()
            else:
                buf.append(ch)
                sys.stdout.write(ch)
                sys.stdout.flush()
        else:
            time.sleep(0.05)


def _unix_reader(put: Callable[[str], None], stop: threading.Event) -> None:
    """Unix non-blocking stdin reader using select."""
    import select

    buf: list[str] = []
    while not stop.is_set():
        ready, _, _ = select.select([sys.stdin], [], [], 0.1)
        if ready:
            ch = sys.stdin.read(1)
            if ch == "\n" or ch == "":
                line = "".join(buf).strip()
                buf.clear()
                if line:
                    put(line)
                if ch == "":
                    break
            else:
                buf.append(ch)
