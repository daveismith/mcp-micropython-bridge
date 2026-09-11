"""
raw_repl.py - MicroPython Raw REPL protocol implementation

Sends and receives code using MicroPython's Raw REPL mode.

The Raw REPL flow (following the mpremote implementation):
  1. Ctrl+C twice to cancel whatever is currently running
  2. Ctrl+A to enter Raw REPL mode
     the board returns "raw REPL; CTRL-B to exit\r\n>"
  3. Send the code, then Ctrl+D to trigger execution
     the board returns "OK" and then starts executing
  4. Once execution finishes, stdout\x04stderr\x04> comes back
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from .transport import StreamTransport

# Raw REPL control characters
CTRL_A = b"\x01"   # switch to Raw REPL mode
CTRL_B = b"\x02"   # switch to Normal REPL mode
CTRL_C = b"\x03"   # interrupt execution
CTRL_D = b"\x04"   # execution trigger / response separator

# Timeout constants (seconds)
DEFAULT_TIMEOUT = 10.0
ENTER_TIMEOUT = 5.0


@dataclass
class ReplResult:
    """The result of a Raw REPL execution"""
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.stderr == ""

    def __str__(self) -> str:
        if self.stderr:
            return f"[ERROR]\n{self.stderr}"
        return self.stdout


class RawReplError(Exception):
    """An error relating to a Raw REPL operation"""


class RawRepl:
    """Implementation of the MicroPython Raw REPL protocol (following mpremote)"""

    def __init__(self, stream: StreamTransport) -> None:
        self._stream = stream
        self._read_buffer = bytearray()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def enter(self) -> None:
        """Enter Raw REPL mode. Raises RawReplError on failure."""
        self._read_buffer.clear()
        # Cancel whatever is running so that a prompt appears
        self._stream.send_bytes(CTRL_C)
        self._stream.send_bytes(CTRL_C)
        time.sleep(0.2)
        self._stream.drain_pending_input()

        # Switch to the Raw REPL  (see mpremote: exec_raw)
        self._stream.send_bytes(CTRL_A)
        try:
            # Wait for "raw REPL; CTRL-B to exit\r\n>"
            self._read_until(b"\r\n>", timeout=ENTER_TIMEOUT)
        except TimeoutError:
            # Fallback: some firmware returns a different string
            pass

        # Clear the buffer, just in case
        time.sleep(0.05)
        self._stream.drain_pending_input()

    def exit(self) -> None:
        """Return to Normal REPL mode."""
        self._stream.send_bytes(CTRL_B)
        time.sleep(0.1)
        self._stream.drain_pending_input()
        self._read_buffer.clear()

    def exec_code(self, code: str, timeout: float = DEFAULT_TIMEOUT) -> ReplResult:
        """
        Run code on the Raw REPL and return the result.

        Args:
            code: the Python code to run (multiple lines are fine)
            timeout: total timeout in seconds, from sending the code through
                returning to the Raw REPL

        Returns:
            ReplResult: the execution result, including stdout / stderr

        Raises:
            RawReplError: a communication error or an unexpected response
        """
        if timeout < 0:
            raise ValueError("timeout must be >= 0")

        # Send the code, then Ctrl+D to trigger execution (following mpremote)
        encoded = code.encode("utf-8")
        self._stream.send_bytes(encoded)
        self._stream.send_bytes(CTRL_D)
        self._stream.flush()
        deadline = time.monotonic() + timeout

        # Wait for "OK"
        self._read_until_with_budget(b"OK", deadline=deadline, stage="the 'OK' response")

        # Read stdout up to \x04
        stdout_bytes = self._read_until_with_budget(CTRL_D, deadline=deadline, stage="stdout")

        # Read stderr up to \x04
        stderr_bytes = self._read_until_with_budget(CTRL_D, deadline=deadline, stage="stderr")

        # Read and discard the terminating ">" prompt
        self._read_until_with_budget(b">", deadline=deadline, stage="the return to the Raw REPL prompt")

        return ReplResult(
            stdout=stdout_bytes.decode("utf-8", errors="replace"),
            stderr=stderr_bytes.decode("utf-8", errors="replace"),
        )

    def exec_code_safe(self, code: str, timeout: float = DEFAULT_TIMEOUT) -> ReplResult:
        """
        Convenience method that runs enter() -> exec_code() -> exit() together.
        """
        self.enter()
        try:
            return self.exec_code(code, timeout=timeout)
        finally:
            self.exit()

    # ------------------------------------------------------------------
    # Internal utilities
    # ------------------------------------------------------------------

    def _read_until_with_budget(self, terminator: bytes, deadline: float, stage: str) -> bytes:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise RawReplError(
                f"Timed out before starting to wait for {stage}."
                " exec_code(timeout=...) is the total budget from sending the code"
                " through returning to the Raw REPL."
            )
        try:
            return self._read_until(terminator, timeout=remaining)
        except TimeoutError as e:
            raise RawReplError(f"Timed out while receiving {stage}: {e}") from e

    def _read_until(self, terminator: bytes, timeout: float = DEFAULT_TIMEOUT) -> bytes:
        """
        Read bytes until the terminator appears.
        The terminator itself is not included in the return value.

        For real hardware: read in chunks wherever possible, and push data read
        ahead past the terminator back into the internal buffer. Even a large
        stdout is not read one byte at a time.

        Raises:
            TimeoutError: the terminator did not appear within timeout seconds
        """
        buf = bytearray()
        deadline = time.monotonic() + timeout

        while True:
            if self._read_buffer:
                chunk = bytes(self._read_buffer)
                self._read_buffer.clear()
            else:
                remaining = max(deadline - time.monotonic(), 0.0)
                if remaining <= 0:
                    raise TimeoutError(
                        f"Timed out: {terminator!r} was not received within {timeout:.1f}s."
                        f" Data received so far: {bytes(buf)!r}"
                    )
                chunk = self._stream.read_some(timeout=min(0.25, remaining))

            if chunk:
                buf.extend(chunk)
                idx = buf.find(terminator)
                if idx != -1:
                    end = idx + len(terminator)
                    trailing = buf[end:]
                    if trailing:
                        self._read_buffer[:0] = trailing
                    return bytes(buf[:idx])

            if time.monotonic() >= deadline:
                raise TimeoutError(
                    f"Timed out: {terminator!r} was not received within {timeout:.1f}s."
                    f" Data received so far: {bytes(buf)!r}"
                )
