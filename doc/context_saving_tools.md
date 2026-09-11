# Proposal: Tools for Saving Context

## Purpose

To make the following tasks easy to complete without passing the full text of a file to the LLM.

- File transfer between the local PC and the device
- Checking for differences
- Partial retrieval of only the parts that are needed
- Simple server-side search

The approach is to keep the existing `micropython_read_file` / `micropython_write_file` and add
low-context tools alongside them.

> **Status**: This is a design proposal. Everything in Phases 1 and 2, and the
> `read_lines` / `head_lines` / `tail_lines` tools in Phase 3, have been implemented.
> `micropython_grep_file` (Phase 3) and `micropython_sync_file` / `sync_dir` (Phase 4) are
> **proposals only** and are not part of the shipped tool set.

---

## Priority

1. `upload` / `download`
2. `hash` / `compare`
3. `read_lines` / `head_lines` / `tail_lines` / `grep`
4. `sync_dir`, if it turns out to be needed later

---

## Phase 1: Transfer

### `micropython_upload_file`

Transfers a local file to the device.

```python
def micropython_upload_file(
    local_path: str,
    remote_path: str,
    timeout: int = 20,
    overwrite: bool = True,
) -> UploadFileResult:
    ...
```

Proposed return value:

```python
class UploadFileResult(TypedDict):
    ok: bool
    local_path: str
    remote_path: str
    bytes_written: int
    sha256: str | None
    error: str | None
```

Specification:

- `local_path` is a host-side path
- `remote_path` is a device-side path
- Read the file on the host and reuse the existing `_write_file_bytes()`
- Fail if `overwrite=False` and the file already exists
- On success, return the `sha256` of the uploaded content

Use cases:

- Transfer `main.py` or an asset as-is, without passing its text to the LLM

### `micropython_download_file`

Saves a device file locally.

```python
def micropython_download_file(
    remote_path: str,
    local_path: str,
    timeout: int = 20,
    overwrite: bool = False,
) -> DownloadFileResult:
    ...
```

Proposed return value:

```python
class DownloadFileResult(TypedDict):
    ok: bool
    remote_path: str
    local_path: str
    bytes_written: int
    sha256: str | None
    error: str | None
```

Specification:

- Retrieve `remote_path` with `_read_file_bytes()`
- Allow `local_path` only underneath the workspace
- Fail if the parent directory does not exist
- Fail if `overwrite=False` and the file already exists

Use cases:

- Taking a backup
- Saving a copy for comparison
- Using a local diff tool

---

## Phase 2: Difference checking

### `micropython_hash_file`

Returns a content hash of a device file.

```python
def micropython_hash_file(
    path: str,
    algorithm: str = "sha256",
    timeout: int = 10,
) -> HashFileResult:
    ...
```

Proposed return value:

```python
class HashFileResult(TypedDict):
    ok: bool
    path: str
    algorithm: str
    digest: str
    size_bytes: int
    error: str | None
```

Specification:

- The initial implementation runs `hashlib.sha256` on the host after `_read_file_bytes()`
- It may be moved to a device-side implementation in the future

Use cases:

- Only needing to know whether there is a difference
- Deciding whether a re-transfer is necessary

### `micropython_compare_local_remote`

Decides whether the local and device files match.

```python
def micropython_compare_local_remote(
    local_path: str,
    remote_path: str,
    timeout: int = 10,
) -> CompareLocalRemoteResult:
    ...
```

Proposed return value:

```python
class CompareLocalRemoteResult(TypedDict):
    ok: bool
    local_path: str
    remote_path: str
    local_sha256: str | None
    remote_sha256: str | None
    same: bool
    error: str | None
```

Use cases:

- Deciding whether they match without passing the text to the LLM
- A foundation for implementing `sync`

---

## Phase 3: Partial retrieval and search

### `micropython_read_lines`

Returns part of a file, by line.

```python
def micropython_read_lines(
    path: str,
    start_line: int = 1,
    max_lines: int = 50,
    timeout: int = 10,
    encoding: str = "utf-8",
    errors: str = "strict",
) -> ReadFileLinesResult:
    ...
```

Proposed return value:

```python
class ReadFileLinesResult(TypedDict):
    ok: bool
    path: str
    start_line: int
    line_count: int
    content: str
    eof: bool
    error: str | None
```

Use cases:

- Checking a few lines of code before and after a point
- Checking part of a log
- Passing content to the LLM with line numbers

### `micropython_head_lines`

Returns only the first N lines.

```python
def micropython_head_lines(
    path: str,
    lines: int = 40,
    timeout: int = 10,
    encoding: str = "utf-8",
    errors: str = "strict",
) -> ReadTextExcerptResult:
    ...
```

### `micropython_tail_lines`

Returns only the last N lines.

```python
def micropython_tail_lines(
    path: str,
    lines: int = 40,
    timeout: int = 10,
    encoding: str = "utf-8",
    errors: str = "strict",
) -> ReadTextExcerptResult:
    ...
```

Proposed shared return value:

```python
class ReadTextExcerptResult(TypedDict):
    ok: bool
    path: str
    content: str
    line_count: int
    truncated: bool
    error: str | None
```

Use cases:

- Checking `/boot.py` or a log
- Checking only a trailing error

### `micropython_grep_file` (proposal, not implemented)

Simple string search.

```python
def micropython_grep_file(
    path: str,
    pattern: str,
    timeout: int = 10,
    ignore_case: bool = False,
    max_matches: int = 20,
) -> GrepFileResult:
    ...
```

Proposed return value:

```python
class GrepMatch(TypedDict):
    line_no: int
    line: str


class GrepFileResult(TypedDict):
    ok: bool
    path: str
    pattern: str
    matches: list[GrepMatch]
    truncated: bool
    error: str | None
```

Specification:

- Substring matching is sufficient, before reaching for regular expressions
- Cut off at `max_matches`

Use cases:

- `import wifi_config`
- `Pin(`
- `webrepl.start`

---

## Phase 4: Future synchronization (proposal, not implemented)

### `micropython_sync_file`

Compares the local and device files and transfers only when there is a difference.

```python
def micropython_sync_file(
    local_path: str,
    remote_path: str,
    timeout: int = 20,
) -> SyncFileResult:
    ...
```

Proposed return value:

```python
class SyncFileResult(TypedDict):
    ok: bool
    local_path: str
    remote_path: str
    changed: bool
    bytes_written: int
    local_sha256: str | None
    remote_sha256_before: str | None
    remote_sha256_after: str | None
    error: str | None
```

Building `sync_dir` on top of this is the safer arrangement.

---

## Implementation notes

Files affected:

- `src/mcp_micropython/tools/filesystem.py`
- `README.md`
- `tests/test_filesystem_tools.py`, if needed

Existing code that could be reused:

- `_read_file_bytes()`
- `_write_file_bytes()`
- `_resolve_write_bytes()`

Helpers to add for host-side processing:

```python
def _compute_sha256(data: bytes) -> str: ...
def _ensure_local_workspace_path(local_path: str) -> Path: ...
def _read_local_file_bytes(local_path: str) -> bytes: ...
def _write_local_file_bytes(local_path: str, data: bytes, overwrite: bool) -> int: ...
```

---

## Safety measures

- `download` may only save underneath the workspace
- `upload` / `download` require `overwrite` to be explicit
- Impose a size limit for very large files
- `grep` must always have a `max_matches`
- `read_lines` has a `max_lines` upper bound

---

## Minimum implementation set

For a first pass, the following alone is enough.

- `micropython_upload_file`
- `micropython_download_file`
- `micropython_hash_file`
- `micropython_compare_local_remote`
- `micropython_read_lines`
- `micropython_head_lines`
- `micropython_tail_lines`

These seven alone considerably increase how much can be done without transcribing full file contents.
