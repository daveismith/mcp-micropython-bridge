"""
filesystem.py - filesystem tools

MCP tools:
  - micropython_list_files       : list files and directories
  - micropython_stat_path        : get information about a path
  - micropython_read_file        : read the contents of a file
  - micropython_read_lines       : read a text file by line
  - micropython_head_lines       : read the first lines of a text file
  - micropython_tail_lines       : read the last lines of a text file
  - micropython_read_hardware_md : read /HARDWARE.md on the device
  - micropython_write_file       : write to a file
  - micropython_append_file      : append to a file
  - micropython_delete_file      : delete a file
  - micropython_make_dir         : create a directory
  - micropython_remove_dir       : remove an empty directory
  - micropython_rename_path      : rename a path
"""

from __future__ import annotations

import ast
import base64
import hashlib
from pathlib import Path
from typing import TypedDict

from mcp.server.fastmcp import FastMCP

from ..raw_repl import RawReplError
from ..session_manager import NotConnectedError, SessionManager

HARDWARE_MD_PATH = "/HARDWARE.md"
FILE_CHUNK_SIZE = 256
STAT_DIR_MASK = 0x4000


class FileEntry(TypedDict):
    name: str
    path: str
    kind: str
    size_bytes: int | None
    mode: int | None


class ListFilesResult(TypedDict):
    ok: bool
    path: str
    entries: list[FileEntry]
    error: str | None


class ReadFileResult(TypedDict):
    ok: bool
    path: str
    content: str
    content_base64: str | None
    size_bytes: int
    error: str | None


class UploadFileResult(TypedDict):
    ok: bool
    local_path: str
    remote_path: str
    bytes_written: int
    sha256: str | None
    error: str | None


class DownloadFileResult(TypedDict):
    ok: bool
    remote_path: str
    local_path: str
    bytes_written: int
    sha256: str | None
    error: str | None


class HashFileResult(TypedDict):
    ok: bool
    path: str
    algorithm: str
    digest: str
    size_bytes: int
    error: str | None


class CompareLocalRemoteResult(TypedDict):
    ok: bool
    local_path: str
    remote_path: str
    local_sha256: str | None
    remote_sha256: str | None
    same: bool
    error: str | None


class ReadLinesResult(TypedDict):
    ok: bool
    path: str
    start_line: int
    line_count: int
    content: str
    eof: bool
    error: str | None


class ReadTextExcerptResult(TypedDict):
    ok: bool
    path: str
    content: str
    line_count: int
    truncated: bool
    error: str | None


class WriteFileResult(TypedDict):
    ok: bool
    path: str
    bytes_written: int
    error: str | None


class DeleteFileResult(TypedDict):
    ok: bool
    path: str
    error: str | None


class StatPathResult(TypedDict):
    ok: bool
    path: str
    kind: str | None
    size_bytes: int | None
    mode: int | None
    mtime: int | None
    error: str | None


class MakeDirResult(TypedDict):
    ok: bool
    path: str
    parents: bool
    error: str | None


class RenamePathResult(TypedDict):
    ok: bool
    src: str
    dst: str
    error: str | None


def register(mcp: FastMCP, manager: SessionManager) -> None:
    """Register the filesystem tools with the MCP server"""

    def _path_join(parent: str, name: str) -> str:
        if parent in ("", "/"):
            return f"/{name}"
        return f"{parent.rstrip('/')}/{name}"

    def _kind_from_mode(mode: int | None) -> str:
        if mode is None:
            return "unknown"
        return "dir" if (mode & STAT_DIR_MASK) else "file"

    def _exec_simple(code: str, *, timeout: float, default_error: str) -> tuple[bool, str | None]:
        try:
            result = manager.exec_code(code, timeout=timeout)
        except NotConnectedError as e:
            return False, str(e)
        except Exception as e:
            return False, str(e)

        if not result.ok:
            return False, result.stderr.strip() or default_error

        stdout = result.stdout.strip()
        if stdout == "OK":
            return True, None
        if stdout.startswith("ERROR:"):
            return False, stdout[len("ERROR:") :].strip() or default_error
        return False, stdout or default_error

    def _chunk_bytes(data: bytes, chunk_size: int = FILE_CHUNK_SIZE) -> list[bytes]:
        return [data[offset : offset + chunk_size] for offset in range(0, len(data), chunk_size)]

    def _read_file_bytes(path: str, timeout: float) -> tuple[bytes | None, str | None]:
        try:
            with manager.raw_repl() as repl:
                repl.enter()
                try:
                    open_result = repl.exec_code(f"f=open({path!r}, 'rb')\nr=f.read", timeout=timeout)
                    if not open_result.ok:
                        return None, open_result.stderr.strip() or "read file failed"

                    chunks = bytearray()
                    while True:
                        chunk_result = repl.exec_code(
                            f"print(repr(r({FILE_CHUNK_SIZE})))",
                            timeout=timeout,
                        )
                        if not chunk_result.ok:
                            return None, chunk_result.stderr.strip() or "read file failed"

                        chunk_text = chunk_result.stdout.strip()
                        if chunk_text.startswith("ERROR:"):
                            return None, chunk_text[len("ERROR:") :].strip() or "read file failed"
                        if not chunk_text:
                            return None, "empty chunk response while reading file"

                        chunk = ast.literal_eval(chunk_text)
                        if not isinstance(chunk, bytes):
                            return None, "unexpected read chunk type"
                        if not chunk:
                            break
                        chunks.extend(chunk)
                finally:
                    repl.exec_code(
                        "try:\n f.close()\nexcept Exception:\n pass",
                        timeout=timeout,
                    )
                    repl.exit()
        except NotConnectedError as e:
            return None, str(e)
        except (RawReplError, SyntaxError, ValueError) as e:
            return None, str(e)
        except Exception as e:
            return None, str(e)

        return bytes(chunks), None

    def _write_file_bytes(path: str, data: bytes, mode: str, timeout: float) -> WriteFileResult:
        try:
            with manager.raw_repl() as repl:
                repl.enter()
                try:
                    open_result = repl.exec_code(f"f=open({path!r}, {mode!r})\nw=f.write", timeout=timeout)
                    if not open_result.ok:
                        return {
                            "ok": False,
                            "path": path,
                            "bytes_written": 0,
                            "error": open_result.stderr.strip() or "write file failed",
                        }

                    written = 0
                    for chunk in _chunk_bytes(data):
                        result = repl.exec_code(f"w({chunk!r})", timeout=timeout)
                        if not result.ok:
                            return {
                                "ok": False,
                                "path": path,
                                "bytes_written": written,
                                "error": result.stderr.strip() or "write file failed",
                            }
                        written += len(chunk)
                finally:
                    repl.exec_code(
                        "try:\n f.close()\nexcept Exception:\n pass",
                        timeout=timeout,
                    )
                    repl.exit()
        except NotConnectedError as e:
            return {"ok": False, "path": path, "bytes_written": 0, "error": str(e)}
        except RawReplError as e:
            return {"ok": False, "path": path, "bytes_written": 0, "error": str(e)}
        except Exception as e:
            return {"ok": False, "path": path, "bytes_written": 0, "error": str(e)}

        return {
            "ok": True,
            "path": path,
            "bytes_written": len(data),
            "error": None,
        }

    def _resolve_write_bytes(
        *,
        content: str | None,
        content_base64: str | None,
        encoding: str,
    ) -> tuple[bytes | None, str | None]:
        if (content is None) == (content_base64 is None):
            return None, "exactly one of content or content_base64 must be provided"

        if content_base64 is not None:
            try:
                return base64.b64decode(content_base64, validate=True), None
            except Exception as e:
                return None, f"invalid base64 content: {e}"

        try:
            assert content is not None
            return content.encode(encoding), None
        except Exception as e:
            return None, str(e)

    def _compute_sha256(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    def _workspace_root() -> Path:
        return Path.cwd().resolve()

    def _ensure_local_workspace_path(local_path: str) -> tuple[Path | None, str | None]:
        try:
            path = Path(local_path)
            resolved = path.resolve() if path.is_absolute() else (_workspace_root() / path).resolve()
            resolved.relative_to(_workspace_root())
            return resolved, None
        except Exception:
            return None, "local path must stay within the workspace"

    def _read_local_file_bytes(local_path: str) -> tuple[bytes | None, Path | None, str | None]:
        resolved, error = _ensure_local_workspace_path(local_path)
        if error is not None or resolved is None:
            return None, None, error
        try:
            return resolved.read_bytes(), resolved, None
        except Exception as e:
            return None, resolved, str(e)

    def _write_local_file_bytes(local_path: str, data: bytes, overwrite: bool) -> tuple[int, Path | None, str | None]:
        resolved, error = _ensure_local_workspace_path(local_path)
        if error is not None or resolved is None:
            return 0, None, error
        if resolved.exists() and not overwrite:
            return 0, resolved, "local file already exists"
        if not resolved.parent.exists():
            return 0, resolved, "parent directory does not exist"
        try:
            resolved.write_bytes(data)
        except Exception as e:
            return 0, resolved, str(e)
        return len(data), resolved, None

    def _read_text_file(path: str, timeout: int, encoding: str, errors: str) -> tuple[str | None, int, str | None]:
        data, error = _read_file_bytes(path, float(timeout))
        if error is not None or data is None:
            return None, 0, error or "read file failed"
        try:
            return data.decode(encoding, errors=errors), len(data), None
        except Exception as e:
            return None, len(data), str(e)

    def _split_lines(content: str, *, keepends: bool = False) -> list[str]:
        return content.splitlines(keepends=keepends)

    def _stat_path(path: str) -> StatPathResult:
        code = f"""\
import os
try:
    print(repr(os.stat({path!r})))
except Exception as e:
    print(f'ERROR: {{e}}')
"""
        try:
            result = manager.exec_code(code, timeout=5.0)
        except NotConnectedError as e:
            return {
                "ok": False,
                "path": path,
                "kind": None,
                "size_bytes": None,
                "mode": None,
                "mtime": None,
                "error": str(e),
            }
        except Exception as e:
            return {
                "ok": False,
                "path": path,
                "kind": None,
                "size_bytes": None,
                "mode": None,
                "mtime": None,
                "error": str(e),
            }

        if not result.ok:
            return {
                "ok": False,
                "path": path,
                "kind": None,
                "size_bytes": None,
                "mode": None,
                "mtime": None,
                "error": result.stderr.strip() or "stat path failed",
            }

        text = result.stdout.strip()
        if text.startswith("ERROR:"):
            return {
                "ok": False,
                "path": path,
                "kind": None,
                "size_bytes": None,
                "mode": None,
                "mtime": None,
                "error": text[len("ERROR:") :].strip(),
            }

        try:
            stat_result = ast.literal_eval(text)
        except Exception:
            return {
                "ok": False,
                "path": path,
                "kind": None,
                "size_bytes": None,
                "mode": None,
                "mtime": None,
                "error": f"unexpected stat output: {text!r}",
            }

        if not isinstance(stat_result, tuple) or len(stat_result) < 9:
            return {
                "ok": False,
                "path": path,
                "kind": None,
                "size_bytes": None,
                "mode": None,
                "mtime": None,
                "error": f"unexpected stat output: {stat_result!r}",
            }

        mode = stat_result[0] if isinstance(stat_result[0], int) else None
        size = stat_result[6] if isinstance(stat_result[6], int) else None
        mtime = stat_result[8] if isinstance(stat_result[8], int) else None
        return {
            "ok": True,
            "path": path,
            "kind": _kind_from_mode(mode),
            "size_bytes": size,
            "mode": mode,
            "mtime": mtime,
            "error": None,
        }

    def _hash_remote_file(path: str, timeout: int, algorithm: str = "sha256") -> HashFileResult:
        if algorithm.lower() != "sha256":
            return {
                "ok": False,
                "path": path,
                "algorithm": algorithm,
                "digest": "",
                "size_bytes": 0,
                "error": "unsupported hash algorithm",
            }

        data, error = _read_file_bytes(path, float(timeout))
        if error is not None or data is None:
            return {
                "ok": False,
                "path": path,
                "algorithm": "sha256",
                "digest": "",
                "size_bytes": 0,
                "error": error or "hash file failed",
            }

        return {
            "ok": True,
            "path": path,
            "algorithm": "sha256",
            "digest": _compute_sha256(data),
            "size_bytes": len(data),
            "error": None,
        }

    @mcp.tool()
    def micropython_list_files(path: str = "/") -> ListFilesResult:
        """
        List the files and directories on the MicroPython board's filesystem

        Args:
            path: the path of the directory to list (default: "/")
        """
        code = f"""\
import os
try:
    for entry in os.ilistdir({path!r}):
        print(repr(entry))
except Exception as e:
    print(f'ERROR: {{e}}')
"""
        try:
            result = manager.exec_code(code, timeout=5.0)
        except NotConnectedError as e:
            return {"ok": False, "path": path, "entries": [], "error": str(e)}
        except Exception as e:
            return {"ok": False, "path": path, "entries": [], "error": str(e)}

        if not result.ok:
            return {
                "ok": False,
                "path": path,
                "entries": [],
                "error": result.stderr.strip() or "list files failed",
            }

        entries: list[FileEntry] = []
        for line in result.stdout.splitlines():
            text = line.strip()
            if not text:
                continue
            if text.startswith("ERROR:"):
                return {
                    "ok": False,
                    "path": path,
                    "entries": [],
                    "error": text[len("ERROR:") :].strip(),
                }

            try:
                raw_entry = ast.literal_eval(text)
            except Exception:
                return {
                    "ok": False,
                    "path": path,
                    "entries": [],
                    "error": f"unexpected ilistdir output: {text!r}",
                }

            if not isinstance(raw_entry, tuple) or len(raw_entry) < 2:
                return {
                    "ok": False,
                    "path": path,
                    "entries": [],
                    "error": f"unexpected ilistdir entry: {raw_entry!r}",
                }

            name = raw_entry[0]
            mode = raw_entry[1]
            size = raw_entry[3] if len(raw_entry) >= 4 else None
            if not isinstance(name, str) or not isinstance(mode, int):
                return {
                    "ok": False,
                    "path": path,
                    "entries": [],
                    "error": f"unexpected ilistdir entry: {raw_entry!r}",
                }

            entries.append(
                {
                    "name": name,
                    "path": _path_join(path, name),
                    "kind": _kind_from_mode(mode),
                    "size_bytes": size if isinstance(size, int) else None,
                    "mode": mode,
                }
            )

        return {
            "ok": True,
            "path": path,
            "entries": entries,
            "error": None,
        }

    @mcp.tool()
    def micropython_stat_path(path: str) -> StatPathResult:
        """
        Get information about a path on the MicroPython board

        Args:
            path: the target path

        Returns:
            ok: True if retrieval succeeded
            path: the target path
            kind: one of `file`, `dir`, or `unknown`
            size_bytes: the file size
            mode: the mode value from `os.stat()`
            mtime: the modification time
            error: the message on failure
        """
        return _stat_path(path)

    @mcp.tool()
    def micropython_read_file(
        path: str,
        timeout: int = 5,
        encoding: str = "utf-8",
        errors: str = "strict",
        as_base64: bool = False,
    ) -> ReadFileResult:
        """
        Read a file from the MicroPython board and return it

        Args:
            path: the path of the file to read (e.g. "/main.py")
            timeout: total timeout in seconds, from sending the code through returning to the Raw REPL
            encoding: the encoding used to decode the text
            errors: the error handling used when decoding the text
            as_base64: when True, leave `content` empty and return base64 in `content_base64`

        Returns:
            ok: True if reading succeeded
            path: the path of the file that was read
            content: the text content; an empty string when `as_base64=True`
            content_base64: the base64 content; None when `as_base64=False`
            size_bytes: the number of bytes read
            error: the message on failure
        """
        data, error = _read_file_bytes(path, float(timeout))
        if error is not None or data is None:
            return {
                "ok": False,
                "path": path,
                "content": "",
                "content_base64": None,
                "size_bytes": 0,
                "error": error or "read file failed",
            }

        if as_base64:
            return {
                "ok": True,
                "path": path,
                "content": "",
                "content_base64": base64.b64encode(data).decode("ascii"),
                "size_bytes": len(data),
                "error": None,
            }

        try:
            content = data.decode(encoding, errors=errors)
        except Exception as e:
            return {
                "ok": False,
                "path": path,
                "content": "",
                "content_base64": None,
                "size_bytes": len(data),
                "error": str(e),
            }

        return {
            "ok": True,
            "path": path,
            "content": content,
            "content_base64": None,
            "size_bytes": len(data),
            "error": None,
        }

    @mcp.tool()
    def micropython_read_hardware_md(timeout: int = 5) -> ReadFileResult:
        """
        Read /HARDWARE.md from the device and return it

        Args:
            timeout: total timeout in seconds, from sending the code through returning to the Raw REPL
        """
        data, error = _read_file_bytes(HARDWARE_MD_PATH, float(timeout))
        if error is not None or data is None:
            return {
                "ok": False,
                "path": HARDWARE_MD_PATH,
                "content": "",
                "content_base64": None,
                "size_bytes": 0,
                "error": error or "read file failed",
            }

        try:
            content = data.decode("utf-8", errors="strict")
        except Exception as e:
            return {
                "ok": False,
                "path": HARDWARE_MD_PATH,
                "content": "",
                "content_base64": None,
                "size_bytes": len(data),
                "error": str(e),
            }

        return {
            "ok": True,
            "path": HARDWARE_MD_PATH,
            "content": content,
            "content_base64": None,
            "size_bytes": len(data),
            "error": None,
        }

    @mcp.tool()
    def micropython_upload_file(
        local_path: str,
        remote_path: str,
        timeout: int = 20,
        overwrite: bool = True,
    ) -> UploadFileResult:
        """
        Transfer a local file to the MicroPython board

        Args:
            local_path: the host-side file path; only paths inside the workspace are allowed
            remote_path: the device-side file path
            timeout: total timeout in seconds, from sending the code through returning to the Raw REPL
            overwrite: when False, do not overwrite an existing file

        Returns:
            ok: True if the transfer succeeded
            local_path: the local path that was read
            remote_path: the device-side path that was written
            bytes_written: the number of bytes written
            sha256: the sha256 of the transferred content; None on failure
            error: the message on failure
        """
        data, resolved_local_path, error = _read_local_file_bytes(local_path)
        local_path_value = str(resolved_local_path) if resolved_local_path is not None else local_path
        if error is not None or data is None:
            return {
                "ok": False,
                "local_path": local_path_value,
                "remote_path": remote_path,
                "bytes_written": 0,
                "sha256": None,
                "error": error or "upload file failed",
            }

        if not overwrite:
            stat_result = _stat_path(remote_path)
            if stat_result["ok"]:
                return {
                    "ok": False,
                    "local_path": local_path_value,
                    "remote_path": remote_path,
                    "bytes_written": 0,
                    "sha256": None,
                    "error": "remote file already exists",
                }

        write_result = _write_file_bytes(remote_path, data, mode="wb", timeout=float(timeout))
        return {
            "ok": write_result["ok"],
            "local_path": local_path_value,
            "remote_path": remote_path,
            "bytes_written": write_result["bytes_written"],
            "sha256": _compute_sha256(data) if write_result["ok"] else None,
            "error": write_result["error"],
        }

    @mcp.tool()
    def micropython_download_file(
        remote_path: str,
        local_path: str,
        timeout: int = 20,
        overwrite: bool = False,
    ) -> DownloadFileResult:
        """
        Save a file from the MicroPython board to the local machine.

        Args:
            remote_path: the device-side file path
            local_path: the host-side destination path; only paths inside the workspace are allowed
            timeout: total timeout in seconds, from sending the code through returning to the Raw REPL
            overwrite: when False, do not overwrite an existing file

        Returns:
            ok: True if saving succeeded
            remote_path: the device-side path that was read
            local_path: the local path that was saved
            bytes_written: the number of bytes saved
            sha256: the sha256 of the saved content; None on failure
            error: the message on failure
        """
        resolved_local_path, path_error = _ensure_local_workspace_path(local_path)
        local_path_value = str(resolved_local_path) if resolved_local_path is not None else local_path
        if path_error is not None:
            return {
                "ok": False,
                "remote_path": remote_path,
                "local_path": local_path_value,
                "bytes_written": 0,
                "sha256": None,
                "error": path_error,
            }

        data, error = _read_file_bytes(remote_path, float(timeout))
        if error is not None or data is None:
            return {
                "ok": False,
                "remote_path": remote_path,
                "local_path": local_path_value,
                "bytes_written": 0,
                "sha256": None,
                "error": error or "download file failed",
            }

        bytes_written, resolved_written_path, write_error = _write_local_file_bytes(local_path, data, overwrite)
        local_path_value = str(resolved_written_path) if resolved_written_path is not None else local_path_value
        return {
            "ok": write_error is None,
            "remote_path": remote_path,
            "local_path": local_path_value,
            "bytes_written": bytes_written,
            "sha256": _compute_sha256(data) if write_error is None else None,
            "error": write_error,
        }

    @mcp.tool()
    def micropython_hash_file(
        path: str,
        algorithm: str = "sha256",
        timeout: int = 10,
    ) -> HashFileResult:
        """
        Return a hash of a file on the MicroPython board.

        Args:
            path: the target file path
            algorithm: the hash algorithm; currently only sha256
            timeout: total timeout in seconds, from sending the code through returning to the Raw REPL
        """
        return _hash_remote_file(path, timeout, algorithm)

    @mcp.tool()
    def micropython_compare_local_remote(
        local_path: str,
        remote_path: str,
        timeout: int = 10,
    ) -> CompareLocalRemoteResult:
        """
        Check whether a local file and a file on the device match.

        Args:
            local_path: the host-side file path; only paths inside the workspace are allowed
            remote_path: the device-side file path
            timeout: total timeout in seconds, from sending the code through returning to the Raw REPL

        Returns:
            ok: True if the comparison succeeded
            local_path: the local path that was compared
            remote_path: the device-side path that was compared
            local_sha256: the sha256 of the local file
            remote_sha256: the sha256 of the device-side file
            same: True if the two match
            error: the message on failure

        Notes:
            The comparison is done with sha256 hashes.
        """
        local_data, resolved_local_path, local_error = _read_local_file_bytes(local_path)
        local_path_value = str(resolved_local_path) if resolved_local_path is not None else local_path
        if local_error is not None or local_data is None:
            return {
                "ok": False,
                "local_path": local_path_value,
                "remote_path": remote_path,
                "local_sha256": None,
                "remote_sha256": None,
                "same": False,
                "error": local_error or "compare failed",
            }
        local_sha256 = _compute_sha256(local_data)

        remote_hash = _hash_remote_file(remote_path, timeout)
        if not remote_hash["ok"]:
            return {
                "ok": False,
                "local_path": local_path_value,
                "remote_path": remote_path,
                "local_sha256": local_sha256,
                "remote_sha256": None,
                "same": False,
                "error": remote_hash["error"],
            }
        remote_sha256 = remote_hash["digest"]

        return {
            "ok": True,
            "local_path": local_path_value,
            "remote_path": remote_path,
            "local_sha256": local_sha256,
            "remote_sha256": remote_sha256,
            "same": local_sha256 == remote_sha256,
            "error": None,
        }

    @mcp.tool()
    def micropython_read_lines(
        path: str,
        start_line: int = 1,
        max_lines: int = 50,
        timeout: int = 10,
        encoding: str = "utf-8",
        errors: str = "strict",
    ) -> ReadLinesResult:
        """
        Read part of a text file on the MicroPython board, by line.

        Args:
            path: the target file path
            start_line: the starting line number, 1-based
            max_lines: the maximum number of lines to return
            timeout: total timeout in seconds, from sending the code through returning to the Raw REPL
            encoding: the encoding used to decode the text
            errors: the error handling used when decoding the text

        Returns:
            ok: True if reading succeeded
            path: the target file path
            start_line: the starting line number actually used
            line_count: the number of lines returned
            content: the text returned
            eof: True if the returned range reached the end of the file
            error: the message on failure
        """
        if start_line < 1:
            return {
                "ok": False,
                "path": path,
                "start_line": start_line,
                "line_count": 0,
                "content": "",
                "eof": False,
                "error": "start_line must be >= 1",
            }
        if max_lines < 1:
            return {
                "ok": False,
                "path": path,
                "start_line": start_line,
                "line_count": 0,
                "content": "",
                "eof": False,
                "error": "max_lines must be >= 1",
            }

        content, _, error = _read_text_file(path, timeout, encoding, errors)
        if error is not None or content is None:
            return {
                "ok": False,
                "path": path,
                "start_line": start_line,
                "line_count": 0,
                "content": "",
                "eof": False,
                "error": error or "read file lines failed",
            }

        all_lines = _split_lines(content, keepends=True)
        start_index = start_line - 1
        selected = all_lines[start_index : start_index + max_lines]
        return {
            "ok": True,
            "path": path,
            "start_line": start_line,
            "line_count": len(selected),
            "content": "".join(selected),
            "eof": start_index + len(selected) >= len(all_lines),
            "error": None,
        }

    @mcp.tool()
    def micropython_head_lines(
        path: str,
        lines: int = 40,
        timeout: int = 10,
        encoding: str = "utf-8",
        errors: str = "strict",
    ) -> ReadTextExcerptResult:
        """
        Return the first few lines of a text file on the MicroPython board.

        Args:
            path: the target file path
            lines: the maximum number of lines to return
            timeout: total timeout in seconds, from sending the code through returning to the Raw REPL
            encoding: the encoding used to decode the text
            errors: the error handling used when decoding the text

        Returns:
            ok: True if reading succeeded
            path: the target file path
            content: the text returned
            line_count: the number of lines returned
            truncated: True when there are remaining lines that could not be returned
            error: the message on failure
        """
        if lines < 1:
            return {"ok": False, "path": path, "content": "", "line_count": 0, "truncated": False, "error": "lines must be >= 1"}

        content, _, error = _read_text_file(path, timeout, encoding, errors)
        if error is not None or content is None:
            return {
                "ok": False,
                "path": path,
                "content": "",
                "line_count": 0,
                "truncated": False,
                "error": error or "head file failed",
            }

        all_lines = _split_lines(content, keepends=True)
        excerpt_lines = all_lines[:lines]
        return {
            "ok": True,
            "path": path,
            "content": "".join(excerpt_lines),
            "line_count": len(excerpt_lines),
            "truncated": len(excerpt_lines) < len(all_lines),
            "error": None,
        }

    @mcp.tool()
    def micropython_tail_lines(
        path: str,
        lines: int = 40,
        timeout: int = 10,
        encoding: str = "utf-8",
        errors: str = "strict",
    ) -> ReadTextExcerptResult:
        """
        Return the last few lines of a text file on the MicroPython board.

        Args:
            path: the target file path
            lines: the maximum number of lines to return
            timeout: total timeout in seconds, from sending the code through returning to the Raw REPL
            encoding: the encoding used to decode the text
            errors: the error handling used when decoding the text

        Returns:
            ok: True if reading succeeded
            path: the target file path
            content: the text returned
            line_count: the number of lines returned
            truncated: True when there are earlier lines that could not be returned
            error: the message on failure
        """
        if lines < 1:
            return {"ok": False, "path": path, "content": "", "line_count": 0, "truncated": False, "error": "lines must be >= 1"}

        content, _, error = _read_text_file(path, timeout, encoding, errors)
        if error is not None or content is None:
            return {
                "ok": False,
                "path": path,
                "content": "",
                "line_count": 0,
                "truncated": False,
                "error": error or "tail file failed",
            }

        all_lines = _split_lines(content, keepends=True)
        excerpt_lines = all_lines[-lines:]
        return {
            "ok": True,
            "path": path,
            "content": "".join(excerpt_lines),
            "line_count": len(excerpt_lines),
            "truncated": len(excerpt_lines) < len(all_lines),
            "error": None,
        }

    @mcp.tool()
    def micropython_write_file(
        path: str,
        content: str | None = None,
        timeout: int = 10,
        encoding: str = "utf-8",
        content_base64: str | None = None,
    ) -> WriteFileResult:
        """
        Write content to a file on the MicroPython board (overwriting it).

        Args:
            path: the path of the file to write to (e.g. "/main.py")
            content: the text content to write; mutually exclusive with `content_base64`
            timeout: total timeout in seconds, from sending the code through returning to the Raw REPL
            encoding: the encoding used to turn content into bytes
            content_base64: the data to write, as base64; mutually exclusive with `content`

        Returns:
            ok: True if writing succeeded
            path: the path written to
            bytes_written: the number of bytes written
            error: the message on failure

        Notes:
            Specify exactly one of `content` and `content_base64`.
        """
        data, error = _resolve_write_bytes(
            content=content,
            content_base64=content_base64,
            encoding=encoding,
        )
        if error is not None or data is None:
            return {
                "ok": False,
                "path": path,
                "bytes_written": 0,
                "error": error or "write file failed",
            }
        return _write_file_bytes(path=path, data=data, mode="wb", timeout=float(timeout))

    @mcp.tool()
    def micropython_append_file(
        path: str,
        content: str | None = None,
        timeout: int = 10,
        encoding: str = "utf-8",
        content_base64: str | None = None,
    ) -> WriteFileResult:
        """
        Append content to a file on the MicroPython board.

        Args:
            path: the path of the file to append to (e.g. "/main.py")
            content: the text content to append; mutually exclusive with `content_base64`
            timeout: total timeout in seconds, from sending the code through returning to the Raw REPL
            encoding: the encoding used to turn content into bytes
            content_base64: the data to append, as base64; mutually exclusive with `content`

        Returns:
            ok: True if appending succeeded
            path: the path appended to
            bytes_written: the number of bytes appended by this call
            error: the message on failure

        Notes:
            Specify exactly one of `content` and `content_base64`.
        """
        data, error = _resolve_write_bytes(
            content=content,
            content_base64=content_base64,
            encoding=encoding,
        )
        if error is not None or data is None:
            return {
                "ok": False,
                "path": path,
                "bytes_written": 0,
                "error": error or "append file failed",
            }
        return _write_file_bytes(path=path, data=data, mode="ab", timeout=float(timeout))

    @mcp.tool()
    def micropython_delete_file(path: str) -> DeleteFileResult:
        """
        Delete a file on the MicroPython board.

        Args:
            path: the path of the file to delete (e.g. "/test.py")
        """
        ok, error = _exec_simple(
            f"import os\ntry:\n os.remove({path!r})\n print('OK')\nexcept Exception as e:\n print(f'ERROR: {{e}}')",
            timeout=5.0,
            default_error="delete file failed",
        )
        return {"ok": ok, "path": path, "error": error}

    @mcp.tool()
    def micropython_make_dir(
        path: str,
        parents: bool = False,
        exist_ok: bool = False,
    ) -> MakeDirResult:
        """
        Create a directory on the MicroPython board.

        Args:
            path: the path of the directory to create
            parents: when True, create the parent directories in turn as well
            exist_ok: when True, tolerate an existing directory
        """
        code = f"""\
import os
path = {path!r}
parents = {parents!r}
exist_ok = {exist_ok!r}
try:
    if parents:
        current = ''
        for part in path.split('/'):
            if not part:
                continue
            current += '/' + part
            try:
                os.mkdir(current)
            except OSError:
                try:
                    mode = os.stat(current)[0]
                    if not (mode & {STAT_DIR_MASK}):
                        raise
                except Exception:
                    raise
    else:
        os.mkdir(path)
    print('OK')
except Exception as e:
    if exist_ok:
        try:
            mode = os.stat(path)[0]
            if mode & {STAT_DIR_MASK}:
                print('OK')
            else:
                print(f'ERROR: {{e}}')
        except Exception:
            print(f'ERROR: {{e}}')
    else:
        print(f'ERROR: {{e}}')
"""
        ok, error = _exec_simple(code, timeout=5.0, default_error="make dir failed")
        return {"ok": ok, "path": path, "parents": parents, "error": error}

    @mcp.tool()
    def micropython_remove_dir(path: str) -> DeleteFileResult:
        """
        Remove an empty directory on the MicroPython board.

        Args:
            path: the path of the directory to remove
        """
        ok, error = _exec_simple(
            f"import os\ntry:\n os.rmdir({path!r})\n print('OK')\nexcept Exception as e:\n print(f'ERROR: {{e}}')",
            timeout=5.0,
            default_error="remove dir failed",
        )
        return {"ok": ok, "path": path, "error": error}

    @mcp.tool()
    def micropython_rename_path(src: str, dst: str) -> RenamePathResult:
        """
        Rename or move a path on the MicroPython board.

        Args:
            src: the source path
            dst: the destination path
        """
        ok, error = _exec_simple(
            f"import os\ntry:\n os.rename({src!r}, {dst!r})\n print('OK')\nexcept Exception as e:\n print(f'ERROR: {{e}}')",
            timeout=5.0,
            default_error="rename path failed",
        )
        return {"ok": ok, "src": src, "dst": dst, "error": error}
