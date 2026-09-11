"""
execution.py - code execution tools

MCP tools:
  - micropython_exec : run a block of Python code and return stdout/stderr
  - micropython_eval : evaluate an expression and return the result
"""

from __future__ import annotations

from typing import TypedDict

from mcp.server.fastmcp import FastMCP

from ..session_manager import NotConnectedError, SessionManager


class ExecResult(TypedDict):
    ok: bool
    stdout: str
    stderr: str
    error: str | None


class EvalResult(TypedDict):
    ok: bool
    result: str
    error: str | None


def register(mcp: FastMCP, manager: SessionManager) -> None:
    """Register the code execution tools with the MCP server."""

    @mcp.tool()
    def micropython_exec(code: str, timeout: int = 10) -> ExecResult:
        """
        Run Python code on the MicroPython interpreter.
        Multi-line code can be executed as well.

        Args:
            code: the Python code to run (may span multiple lines)
            timeout: total timeout in seconds, covering everything from sending the code
                through returning to the Raw REPL (default 10 seconds)

        Returns:
            ok: True if execution succeeded
            stdout: standard output
            stderr: standard error output
            error: the message on failure; None on success

        Example:
            code = "import machine\\nprint(machine.freq())"
        """
        try:
            result = manager.exec_code(code, timeout=float(timeout))
        except NotConnectedError as e:
            return {"ok": False, "stdout": "", "stderr": "", "error": str(e)}
        except Exception as e:
            return {"ok": False, "stdout": "", "stderr": "", "error": str(e)}

        return {
            "ok": result.ok,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "error": None if result.ok else (result.stderr.strip() or "execution failed"),
        }

    @mcp.tool()
    def micropython_eval(expression: str) -> EvalResult:
        """
        Evaluate an expression on the MicroPython board and return the result as a string.

        Args:
            expression: the Python expression to evaluate (e.g. "1 + 1", "machine.freq()")

        Returns:
            ok: True if evaluation succeeded
            result: the string representation of the result
            error: the message on failure; None on success
        """
        try:
            result = manager.eval_expr(expression)
        except NotConnectedError as e:
            return {"ok": False, "result": "", "error": str(e)}
        except Exception as e:
            return {"ok": False, "result": "", "error": str(e)}

        if result.ok:
            return {"ok": True, "result": result.stdout.strip(), "error": None}
        else:
            return {
                "ok": False,
                "result": "",
                "error": result.stderr.strip() or "evaluation failed",
            }
