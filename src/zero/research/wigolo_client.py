"""
Wigolo MCP Client for Project ZERO.

Communicates with the local Wigolo MCP server via standard JSON-RPC 2.0 over stdio.
Zero external runtime dependencies (Python standard library only).
Strictly adheres to INR 0 operating budget.
"""

import json
import logging
import os
from pathlib import Path
import queue
import subprocess
import threading
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

DEFAULT_WIGOLO_NODE = "node"
DEFAULT_WIGOLO_SCRIPT = r"D:\wigolo\dist\index.js"


def get_default_wigolo_command() -> List[str]:
    """Retrieve the configured Wigolo command from MCP config or default location."""
    # Check if configured in global mcp_config.json
    config_path = Path.home() / ".gemini" / "config" / "mcp_config.json"
    if config_path.exists():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                wigolo_conf = data.get("mcpServers", {}).get("wigolo", {})
                cmd = wigolo_conf.get("command")
                args = wigolo_conf.get("args", [])
                if cmd and args:
                    return [cmd] + args
        except Exception as e:
            logger.debug("Failed to read mcp_config.json: %s", e)

    return [DEFAULT_WIGOLO_NODE, DEFAULT_WIGOLO_SCRIPT]


class WigoloMcpClient:
    """
    Stdio client for Wigolo Model Context Protocol (MCP) server.
    Supports search and fetch tools with structured response parsing.
    """

    def __init__(
        self,
        command: Optional[List[str]] = None,
        timeout: float = 15.0,
        mock_handler: Optional[Callable[[str, Dict[str, Any]], Dict[str, Any]]] = None,
    ):
        self.command = command or get_default_wigolo_command()
        self.timeout = timeout
        self.mock_handler = mock_handler
        self._process: Optional[subprocess.Popen] = None
        self._output_queue: Optional[queue.Queue] = None
        self._reader_thread: Optional[threading.Thread] = None
        self._msg_id = 0
        self._initialized = False

    def _next_id(self) -> int:
        self._msg_id += 1
        return self._msg_id

    def _reader_loop(self) -> None:
        """Background thread reading lines from process stdout into a queue."""
        while self._process and self._process.stdout:
            try:
                line = self._process.stdout.readline()
                if not line:
                    if self._output_queue:
                        self._output_queue.put("")
                    break
                if self._output_queue:
                    self._output_queue.put(line.strip())
            except Exception:
                break

    def _ensure_process(self) -> None:
        """Start Wigolo stdio process and complete MCP initialize handshake."""
        if self.mock_handler is not None or self._initialized:
            return

        if self._process is None or self._process.poll() is not None:
            # Verify script exists if pointing to a local file
            if len(self.command) > 1 and Path(self.command[1]).suffix in (".js", ".mjs"):
                script_path = Path(self.command[1])
                if not script_path.exists():
                    raise FileNotFoundError(f"Wigolo script not found at {script_path}")

            try:
                self._process = subprocess.Popen(
                    self.command,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                )
                self._output_queue = queue.Queue()
                self._reader_thread = threading.Thread(target=self._reader_loop, daemon=True)
                self._reader_thread.start()
            except Exception as e:
                raise RuntimeError(f"Failed to launch Wigolo MCP server process: {e}") from e

            # Send initialize request
            init_req = {
                "jsonrpc": "2.0",
                "id": self._next_id(),
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "project-zero", "version": "0.3.0"},
                },
            }
            self._write_message(init_req)
            resp = self._read_message(timeout=10.0)
            if "error" in resp:
                raise RuntimeError(f"Wigolo initialization failed: {resp['error']}")

            # Send initialized notification
            notif = {
                "jsonrpc": "2.0",
                "method": "notifications/initialized",
            }
            self._write_message(notif)
            self._initialized = True

    def _write_message(self, msg: Dict[str, Any]) -> None:
        if not self._process or not self._process.stdin:
            raise RuntimeError("Wigolo process is not running")
        line = json.dumps(msg) + "\n"
        self._process.stdin.write(line)
        self._process.stdin.flush()

    def _read_message(self, timeout: Optional[float] = None) -> Dict[str, Any]:
        if not self._output_queue:
            raise RuntimeError("Wigolo process is not running")
        t = timeout or self.timeout
        try:
            line = self._output_queue.get(timeout=t)
        except queue.Empty:
            raise TimeoutError(f"Wigolo response timed out after {t}s")

        if not line:
            stderr_out = self._process.stderr.read() if self._process and self._process.stderr else ""
            raise RuntimeError(f"Wigolo process closed stdout unexpectedly. Stderr: {stderr_out}")
        return json.loads(line)

    def call_tool(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Call a named tool on the Wigolo MCP server."""
        if self.mock_handler is not None:
            return self.mock_handler(name, arguments)

        self._ensure_process()
        req_id = self._next_id()
        msg = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": "tools/call",
            "params": {
                "name": name,
                "arguments": arguments,
            },
        }
        self._write_message(msg)
        resp = self._read_message()

        if "error" in resp:
            raise RuntimeError(f"Wigolo tool '{name}' error: {resp['error']}")

        # Extract text content
        result = resp.get("result", {})
        content_items = result.get("content", [])
        if not content_items:
            return {}

        text_content = content_items[0].get("text", "{}")
        try:
            return json.loads(text_content)
        except json.JSONDecodeError:
            return {"raw_text": text_content}

    def search(
        self,
        query: str,
        max_results: int = 5,
        category: str = "general",
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Execute a web search through Wigolo."""
        args: Dict[str, Any] = {
            "query": query,
            "max_results": max_results,
            "category": category,
        }
        args.update(kwargs)
        try:
            return self.call_tool("search", args)
        except Exception as e:
            logger.warning("Wigolo search failed for query '%s': %s", query, e)
            return {"results": [], "error": str(e), "query": query}

    def fetch(self, url: str, **kwargs: Any) -> Dict[str, Any]:
        """Fetch and extract clean markdown from a single URL through Wigolo."""
        args: Dict[str, Any] = {"url": url}
        args.update(kwargs)
        try:
            return self.call_tool("fetch", args)
        except Exception as e:
            logger.warning("Wigolo fetch failed for url '%s': %s", url, e)
            return {"error": str(e), "url": url}

    def close(self) -> None:
        """Terminate the Wigolo process cleanly."""
        if self._process:
            try:
                self._process.terminate()
                self._process.wait(timeout=2.0)
            except Exception:
                try:
                    self._process.kill()
                except Exception:
                    pass
            finally:
                self._process = None
                self._initialized = False

    def __enter__(self) -> "WigoloMcpClient":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

