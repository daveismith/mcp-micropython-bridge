"""
device.py — connection and device tools.
"""

from __future__ import annotations

from typing import TypedDict

from mcp.server.fastmcp import FastMCP

from ..session_manager import SessionManager
from ..transport import UnsupportedOperationError

# Code that gathers device information (runs on the MicroPython board)
_GET_INFO_CODE = """\
import sys, gc, os
gc.collect()
info = {
    'platform': sys.platform,
    'version': '.'.join(str(v) for v in sys.version_info[:3]),
    'implementation': sys.implementation.name,
    'free_mem': gc.mem_free(),
    'alloc_mem': gc.mem_alloc(),
}
try:
    import machine
    info['freq_mhz'] = machine.freq() // 1_000_000
except Exception:
    pass
try:
    s = os.statvfs('/')
    info['fs_total_kb'] = s[0] * s[2] // 1024
    info['fs_free_kb']  = s[0] * s[3] // 1024
except Exception:
    pass
for k, v in info.items():
    print(f'{k}={v}')
"""


class DeviceInfo(TypedDict, total=False):
    platform: str
    version: str
    implementation: str
    free_mem: int
    alloc_mem: int
    freq_mhz: int
    fs_total_kb: int
    fs_free_kb: int


class GetInfoResult(TypedDict):
    ok: bool
    info: DeviceInfo
    error: str | None


class SerialPortInfo(TypedDict):
    port: str
    description: str
    hwid: str


class ListPortsResult(TypedDict):
    ok: bool
    ports: list[SerialPortInfo]
    error: str | None


class ConnectionResult(TypedDict):
    ok: bool
    target: str
    transport: str | None
    baudrate: int | None
    host: str | None
    port: int | str | None
    error: str | None


class DisconnectResult(TypedDict):
    ok: bool
    error: str | None


class ActionResult(TypedDict):
    ok: bool
    error: str | None


class ConnectionStatusResult(TypedDict):
    ok: bool
    connected: bool
    transport: str | None
    target: str | None
    host: str | None
    port: int | str | None
    baudrate: int | None
    error: str | None


class SerialReadResult(TypedDict):
    ok: bool
    stdout: str
    truncated: bool
    bytes_read: int
    error: str | None


class SerialReadUntilResult(TypedDict):
    ok: bool
    matched: bool
    stdout: str
    bytes_read: int
    error: str | None


class ResetCaptureResult(TypedDict):
    ok: bool
    stdout: str
    reset_ok: bool
    truncated: bool
    error: str | None


def _parse_info_value(raw_value: str) -> str | int:
    raw_value = raw_value.strip()
    try:
        return int(raw_value)
    except ValueError:
        return raw_value


def _parse_device_info(stdout: str) -> DeviceInfo:
    info: DeviceInfo = {}
    for line in stdout.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        info[key] = _parse_info_value(value)
    return info


def register(mcp: FastMCP, manager: SessionManager) -> None:
    """Register the device-related tools with the MCP server."""

    @mcp.tool()
    def micropython_list_ports() -> ListPortsResult:
        """
        List the serial ports available to connect to
        """
        ports = manager.list_ports()
        return {
            "ok": True,
            "ports": [
                {
                    "port": p["port"],
                    "description": p["description"],
                    "hwid": p["hwid"],
                }
                for p in ports
            ],
            "error": None,
        }

    @mcp.tool()
    def micropython_connect(
        target: str,
        password: str | None = None,
        baudrate: int = 115200,
    ) -> ConnectionResult:
        """
        Connect to the given target

        Args:
            target: `COM3` for serial, `host[:port]` for WebREPL
            password: the password, for a WebREPL connection
            baudrate: the baud rate, for a serial connection
        """
        try:
            status = manager.connect(target=target, password=password, baudrate=baudrate)
            return {
                "ok": True,
                "target": target,
                "transport": status.get("transport"),
                "baudrate": status.get("baudrate") if isinstance(status.get("baudrate"), int) else None,
                "host": status.get("host") if isinstance(status.get("host"), str) else None,
                "port": status.get("port"),
                "error": None,
            }
        except Exception as e:
            return {
                "ok": False,
                "target": target,
                "transport": None,
                "baudrate": baudrate,
                "host": None,
                "port": None,
                "error": str(e),
            }

    @mcp.tool()
    def micropython_disconnect() -> DisconnectResult:
        """
        Close the current connection to the MicroPython board
        Returns success even when not connected

        Returns:
            ok: True on success
            error: the message on failure
        """
        if not manager.is_connected:
            return {
                "ok": True,
                "error": None,
            }
        manager.disconnect()
        return {
            "ok": True,
            "error": None,
        }

    @mcp.tool()
    def micropython_connection_status() -> ConnectionStatusResult:
        """
        Return the current connection state

        Returns:
            ok: True on success
            connected: True while connected
            transport: `serial` or `webrepl`
            target: the target given when connecting
            host: the host, for a WebREPL connection
            port: the port connected to
            baudrate: the baud rate, for a serial connection
            error: the message on failure
        """
        status = manager.connection_status()
        return {
            "ok": True,
            "connected": bool(status.get("connected")),
            "transport": status.get("transport") if isinstance(status.get("transport"), str) else None,
            "target": status.get("target") if isinstance(status.get("target"), str) else None,
            "host": status.get("host") if isinstance(status.get("host"), str) else None,
            "port": status.get("port"),
            "baudrate": status.get("baudrate") if isinstance(status.get("baudrate"), int) else None,
            "error": None,
        }

    @mcp.tool()
    def micropython_get_info() -> GetInfoResult:
        """
        Get device information from the MicroPython board

        Returns:
            ok: True on success
            info: the device information retrieved
            error: the message on failure

        Notes:
            `info` includes the following, where available.
            `platform`, `version`, `implementation`,
            `free_mem`, `alloc_mem`, `freq_mhz`,
            `fs_total_kb`, `fs_free_kb`
        """
        try:
            result = manager.exec_code(_GET_INFO_CODE, timeout=5.0)
            if not result.ok:
                return {
                    "ok": False,
                    "info": {},
                    "error": result.stderr.strip() or "device info command failed",
                }
            return {
                "ok": True,
                "info": _parse_device_info(result.stdout),
                "error": None,
            }
        except Exception as e:
            return {
                "ok": False,
                "info": {},
                "error": str(e),
            }

    @mcp.tool()
    def micropython_reset() -> ActionResult:
        """
        Soft reset the MicroPython board (equivalent to machine.reset())
        Reconnection is required after the reset
        """
        try:
            # machine.reset() resets without returning a response, so use a
            # short timeout and ignore the resulting error
            try:
                manager.exec_code("import machine; machine.reset()", timeout=2.0)
            except Exception:
                pass
            manager.disconnect()
            return {"ok": True, "error": None}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    @mcp.tool()
    def micropython_interrupt() -> ActionResult:
        """Send Ctrl-C to interrupt the running program"""
        try:
            manager.interrupt()
            return {"ok": True, "error": None}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    @mcp.tool()
    def micropython_read_stream(
        duration: float,
        idle_timeout: float | None = None,
        max_bytes: int | None = None,
    ) -> SerialReadResult:
        """
        Read streamed output from the connected device for a fixed period of time

        Args:
            duration: the maximum number of seconds to keep reading
            idle_timeout: stop early after this many seconds with no traffic
            max_bytes: the maximum number of bytes to read; exceeding it sets `truncated=True`

        Returns:
            ok: True on success
            stdout: the text that was read
            truncated: True if reading was cut off by `max_bytes`
            bytes_read: the number of bytes actually read
            error: the message on failure
        """
        try:
            result = manager.read_stream(
                duration=duration,
                idle_timeout=idle_timeout,
                max_bytes=max_bytes,
            )
            return {
                "ok": True,
                "stdout": result["stdout"],
                "truncated": result["truncated"],
                "bytes_read": result["bytes_read"],
                "error": None,
            }
        except Exception as e:
            return {
                "ok": False,
                "stdout": "",
                "truncated": False,
                "bytes_read": 0,
                "error": str(e),
            }

    @mcp.tool()
    def micropython_read_until(
        pattern: str,
        timeout: float,
        max_bytes: int | None = None,
    ) -> SerialReadUntilResult:
        """
        Read output from the connected device until the given string appears

        Args:
            pattern: the string to detect; a substring, not a regular expression
            timeout: the maximum number of seconds to wait
            max_bytes: the maximum number of bytes to read

        Returns:
            ok: True on success
            matched: True if `pattern` was detected
            stdout: the text that was read
            bytes_read: the number of bytes actually read
            error: the message on failure
        """
        try:
            result = manager.read_until(
                pattern=pattern,
                timeout=timeout,
                max_bytes=max_bytes,
            )
            return {
                "ok": True,
                "matched": result["matched"],
                "stdout": result["stdout"],
                "bytes_read": result["bytes_read"],
                "error": None,
            }
        except Exception as e:
            return {
                "ok": False,
                "matched": False,
                "stdout": "",
                "bytes_read": 0,
                "error": str(e),
            }

    @mcp.tool()
    def micropython_reset_and_capture(
        capture_duration: float,
        idle_timeout: float | None = None,
        max_bytes: int | None = None,
    ) -> ResetCaptureResult:
        """
        Reset the device and read the output produced right after boot, for a fixed period

        Args:
            capture_duration: the maximum number of seconds to read after the reset
            idle_timeout: stop early after this many seconds with no traffic
            max_bytes: the maximum number of bytes to read; exceeding it sets `truncated=True`

        Returns:
            ok: True if both the reset and the read call succeeded
            stdout: the text captured after boot
            reset_ok: True if the reset operation itself succeeded
            truncated: True if reading was cut off by `max_bytes`
            error: the message on failure
        """
        try:
            result = manager.reset_and_capture(
                capture_duration=capture_duration,
                idle_timeout=idle_timeout,
                max_bytes=max_bytes,
            )
            return {
                "ok": True,
                "stdout": result["stdout"],
                "reset_ok": result["reset_ok"],
                "truncated": result["truncated"],
                "error": None,
            }
        except UnsupportedOperationError as e:
            return {
                "ok": False,
                "stdout": "",
                "reset_ok": False,
                "truncated": False,
                "error": str(e),
            }
        except Exception as e:
            return {
                "ok": False,
                "stdout": "",
                "reset_ok": False,
                "truncated": False,
                "error": str(e),
            }
