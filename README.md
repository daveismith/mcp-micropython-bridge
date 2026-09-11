> **Fork notice** — This is an English-language fork of
> [SWITCHSCIENCE/mcp-micropython-bridge](https://github.com/SWITCHSCIENCE/mcp-micropython-bridge).
> All credit for the original implementation goes to the upstream authors.
> This fork exists only to translate the documentation and tool descriptions
> into English; see upstream for the original Japanese.

# mcp-micropython-bridge

An MCP bridge server for the MicroPython REPL.

Operate MicroPython devices (ESP32, RP2040, etc.) over USB serial or WebREPL from MCP clients
such as Claude Desktop, Codex (VSCode), Copilot (VSCode), and Antigravity.

`HARDWARE.md` is meant to be more than a wiring scratchpad: treat it as board-specific
documentation that future sessions will reuse. For example, when a request to drive a servo
comes in, don't settle for a throwaway snippet. Create a small helper module on the device,
add a short usage note to `HARDWARE.md` only when new usage patterns or assumptions appear,
and reuse that helper from then on.

## Setup

```bash
# Install dependencies
uv sync

# Start the server (to check that it runs)
uv run mcp-micropython-bridge

# Real-device test CLI, driven through the tools wrappers
uv run python -m mcp_micropython.device_test_cli --target COM3          # Windows
uv run python -m mcp_micropython.device_test_cli --target /dev/ttyACM0  # Linux
uv run python -m mcp_micropython.device_test_cli --target /dev/cu.usbmodem101  # macOS
```

## Flashing MicroPython firmware

To use this tool, the MicroPython firmware must be flashed onto the target device itself.
See the [official MicroPython site](https://micropython.org/) for details.

### Download pages by target

- [ESP32](https://micropython.org/download/?mcu=esp32)
- [ESP32-S3](https://micropython.org/download/?mcu=esp32s3)
- [ESP32-C5](https://micropython.org/download/?mcu=esp32c5)
- [RP2040](https://micropython.org/download/?mcu=rp2040)
- [RP2350](https://micropython.org/download/?mcu=rp2350)

### Example install on ESP32 (`esptool.py`)

The ESP32 series can be flashed from the command line with `esptool.py`.

1. Install `esptool`:
   ```bash
   pip install esptool
   ```
2. Erase the existing flash:
   ```bash
   esptool.py --chip esp32 --port COMx erase_flash
   ```
3. Write the new firmware:
   ```bash
   esptool.py --chip esp32 --port COMx --baud 460800 write_flash -z 0x1000 <firmware_file>.bin
   ```
   (Note: depending on the chip variant (esp32, esp32s3, etc.) and its configuration, the write
   address may be `0x0` instead. Follow the instructions on the relevant download page.)


## Registering with an MCP client

Use `claude_desktop_config_example.json` as a reference and add an entry to your client's
configuration file.

```json
{
  "mcpServers": {
    "micropython": {
      "command": "uv",
      "args": [
        "--directory",
        "C:\\mcp-micropython-bridge",
        "run",
        "mcp-micropython-bridge"
      ]
    }
  }
}
```

## Resources provided

| Resource | Description |
|---|---|
| `micropython://guide/recipes` | How to carry out common tasks |
| `micropython://policy/hardware-docs` | When `HARDWARE.md` should be updated |
| `micropython://guide/troubleshooting` | Recovery steps for common problems |
| `micropython://guide/limitations` | List of known limitations |

## Tools provided

| Tool | Description |
|---|---|
| `micropython_list_ports` | List the available serial ports |
| `micropython_connect` | Connect to `COM3` or `host[:port]` |
| `micropython_disconnect` | Close the connection |
| `micropython_connection_status` | Get the current connection state |
| `micropython_exec` | Run Python code, blocking until it completes |
| `micropython_eval` | Evaluate an expression and return its value |
| `micropython_get_info` | Get device information |
| `micropython_reset` | Soft reset |
| `micropython_interrupt` | Send Ctrl-C to interrupt the running program |
| `micropython_read_stream` | Read output for a fixed period of time |
| `micropython_read_until` | Wait until a specific string appears |
| `micropython_reset_and_capture` | Reset the board and capture the boot log (serial only) |
| `micropython_list_files` | List files |
| `micropython_stat_path` | Get information about a path |
| `micropython_read_file` | Read a file |
| `micropython_read_lines` | Read a range of lines |
| `micropython_head_lines` | Read the first few lines |
| `micropython_tail_lines` | Read the last few lines |
| `micropython_read_hardware_md` | Read `/HARDWARE.md` |
| `micropython_upload_file` | Transfer a local file to the device |
| `micropython_download_file` | Save a device file locally |
| `micropython_hash_file` | Get the SHA-256 of a device file |
| `micropython_compare_local_remote` | Check whether a local and a device file match |
| `micropython_write_file` | Write a file |
| `micropython_append_file` | Append to a file |
| `micropython_delete_file` | Delete a file |
| `micropython_make_dir` | Create a directory |
| `micropython_remove_dir` | Remove an empty directory |
| `micropython_rename_path` | Rename a path |

The `timeout` of `micropython_exec(timeout=...)` is treated as a total budget covering everything
from the start of code transmission through the return to the Raw REPL.
The `timeout` of `micropython_read_file` / `micropython_read_hardware_md` / `micropython_write_file` /
`micropython_append_file` has the same meaning.

`micropython_write_file` supports both text writes via `content` and binary writes via `content_base64`.
`micropython_append_file` appends using the same input and output formats.
Using `micropython_read_file(as_base64=True)` retrieves the content with line endings and non-UTF-8
byte sequences preserved.

## Real-device test CLI

This CLI calls the registered tool functions in `src/mcp_micropython/tools` through a `FakeMCP` shim,
running connection checks, file I/O, and the serial-only stream/reset checks against a real device in
one go.

```bash
# Run the extended set over serial
uv run python -m mcp_micropython.device_test_cli --target COM3

# Run only the common tests over WebREPL
uv run python -m mcp_micropython.device_test_cli --target 192.168.1.10:8266 --password secret --tests common,filesystem

# Launch via the entry point
uv run mcp-micropython-device-test --target COM3 --tests all
```

Main options:

- `--target`: `COM3` or `host[:port]` (on macOS/Linux, a device path such as `/dev/cu.usbmodem101` or `/dev/ttyACM0`)
- `--password`: password for WebREPL
- `--baudrate`: serial baud rate
- `--tests`: `all`, `common`, `filesystem`, `serial`, `stream`, `reset`
- `--large-file-size`: size used by the large transfer test
- `--exec-timeout`: timeout for `exec` and file operations
- `--read-timeout`: wait time for `read_until` / `read_stream` / `reset_and_capture`
- `--reconnect-timeout`: how long to wait for the serial port to reappear after a reset

When running `stream` / `reset` over serial, `/main.py` is temporarily replaced in order to verify the
boot log, and then restored to its original contents. `/boot.py` is not modified, but it is read as a
check on that assumption.

## WebREPL prerequisites

To use a WebREPL connection, the target board must already be configured with Wi-Fi connectivity and
`webrepl.start()`.
This MCP server is only responsible for connecting to an already configured WebREPL; it does not
perform the initial setup of `boot.py`.

This repository ships `device_root/boot.py` and `device_root/setup.py` as initial-setup files.

- `device_root/boot.py`
  On device boot, reads the Wi-Fi SSID, Wi-Fi password, and WebREPL password from NVS, then connects
  to Wi-Fi and runs `webrepl.start()`
- `device_root/setup.py`
  A one-time setup script to run from the serial REPL. It saves the values you enter into NVS

Keep the `WEBREPL_PASSWORD` saved by `setup.py` to 8 characters or fewer, as required by MicroPython's
WebREPL.
Credentials are stored in NVS rather than in a file, but they are still held on the physical device, so
handle them with care.

Flow after setup:

1. Over a serial connection, write `device_root/boot.py` to the device as `/boot.py`
2. Over a serial connection, write `device_root/setup.py` to the device as `/setup.py`
3. Run `import setup` in the serial REPL and save the Wi-Fi SSID, Wi-Fi password, and WebREPL password
4. Restart the board
5. Check the IP address assigned on the Wi-Fi side and connect to it
