# WebREPL Support Design Plan

## Overview

The existing MicroPython MCP Bridge assumes a USB serial connection.
WebREPL support keeps the conventional serial workflow intact while letting the same
`micropython_connect` tool handle WebREPL connections as well.

WebREPL support assumes that the board's Wi-Fi connection and `webrepl.start()` have already been
configured outside this MCP server.
The MCP server connects to an already configured WebREPL with
`micropython_connect(target="host[:port]", password="...")`.

---

## Goals

- When WebREPL is not used, keep the conventional `list ports -> connect serial` flow
- When WebREPL is used, allow connecting with the host and password preconfigured on the board
- Keep a single MCP server, switching between serial and WebREPL internally
- Do not keep connection profiles on the host side

---

## Connection paths

### 1. Serial workflow

Normal operation keeps the following flow.

1. `micropython_list_ports`
2. `micropython_connect(target="COMx", baudrate=115200)`
3. Use the existing tools such as `micropython_exec`

### 2. WebREPL workflow

The user completes the initial WebREPL setup through a separate route.
The MCP server connects by specifying the already configured host directly.

1. `micropython_connect(target="192.168.0.10", password="secret")`
2. Use the existing tools such as `micropython_exec`

When `target` is in `host[:port]` form, it is treated as a WebREPL connection.
When the port is omitted, `8266` is used.

---

## Connection management architecture

### Reorganization into SessionManager

Because the previous `SerialManager` carried serial-specific responsibilities, it is reorganized
into the equivalent of a `SessionManager` with an abstracted transport.

- Holds a single currently connected transport
- Provides `connect`, `disconnect`, `exec_code`, `eval_expr`, `interrupt`, and `reset`
- Unifies the stream-reading API to be transport-independent as well
- Constrains serial-only operations explicitly with `require_serial_connection()`

### Transport abstraction

There are two kinds of transport.

- `SerialTransport`
- `WebReplTransport`

The higher-level execution / filesystem / device tools are unaware of the difference between them.

### Handling of the Raw REPL

`raw_repl.py` moves away from assuming serial and toward depending on a REPL-oriented common
interface.

- `send_bytes`
- `read_some`
- `flush`
- `drain_pending_input`

The same REPL execution flow is used for both serial and WebREPL.

---

## Tool design

The connection-related tools are organized as follows.

- `micropython_list_ports`
- `micropython_connect`
- `micropython_disconnect`
- `micropython_connection_status`

### Role of each tool

`micropython_list_ports`

- Lists the available serial ports
- Used to decide the target of an initial serial connection

`micropython_connect`

- Switches between serial and WebREPL through the single `target` argument
- A value such as `COM3` is treated as a serial connection
- A value such as `host[:port]` is treated as a WebREPL connection
- `password` is required for a WebREPL connection
- `baudrate` is used only for a serial connection

`micropython_connection_status`

- Returns the current connection state
- Returns `connected`, `transport`, and `target`
- For serial, also returns `port` and `baudrate`
- For WebREPL, returns `host` and `port`

Initial WebREPL setup and secret management are not part of the MCP server's responsibilities.

---

## Impact on existing tools

Existing tools such as `micropython_exec`, `micropython_eval`, `micropython_list_files`,
`micropython_read_file`, `micropython_write_file`, `micropython_delete_file`,
`micropython_interrupt`, and `micropython_reset` are made usable under the same names whether the
connected transport is serial or WebREPL.

This way only the connection method changes, and the higher-level experience stays as uniform as
possible.

### Reading tools

The output-reading tools move toward transport-common semantics.

- Official name: `micropython_read_stream`
- Official name: `micropython_read_until`
- The old `micropython_serial_read` / `micropython_serial_read_until` remain as compatibility aliases

### Serial-only tools

`micropython_reset_and_capture` remains serial-only.

- Over a serial connection it can be used as before
- When called while connected over WebREPL, it returns an unsupported error

---

## Test considerations

- Current functionality does not regress in the serial workflow
- `micropython_connect("COMx")` can establish a serial connection
- `micropython_connect("host")` / `micropython_connect("host:port")` are interpreted as WebREPL
- The exec/eval/filesystem/device tools work over a WebREPL connection
- `micropython_reset_and_capture` works over serial and is unsupported over WebREPL
- `micropython_read_stream` / `micropython_read_until` work over both serial and WebREPL

---

## Assumptions and accepted limitations

- WebREPL support targets standard MicroPython boards where `webrepl` is available
- The board's Wi-Fi connection and WebREPL activation are preconfigured outside the MCP server
- Only `host[:port]` input is supported for the WebREPL target; URL form, SSL, and path
  specifications are not handled
- The default WebREPL port is `8266`
- No connection profile management is done on the host side
- MCP server registration is not split into multiple servers; the transport is switched within a
  single server
