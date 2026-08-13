import json
import subprocess
import threading
from collections import deque
from typing import Any, Dict, List, Optional

from src.mcp_gateway.protocol.json_rpc import parse_json_rpc
from src.mcp_gateway.protocol.transports.command_resolve import resolve_stdio_launch


class StdioMCPTransport:
    """
    Stdio Subprocess Transport Adapter for MCP Servers.
    Launches server subprocess and communicates via standard stdin/stdout streams.
    """

    def __init__(
        self,
        command: str,
        args: Optional[List[str]] = None,
        env: Optional[Dict[str, str]] = None,
        cwd: Optional[str] = None,
    ):
        self.command = command
        self.args = args or []
        self.env = env
        self.cwd = cwd
        self.process: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()
        self._stderr_tail: deque[str] = deque(maxlen=40)

    def connect(self) -> None:
        """Launches the external MCP server subprocess."""
        command, args, env = resolve_stdio_launch(self.command, self.args, self.env)
        self.process = subprocess.Popen(
            [command, *args],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            env=env,
            cwd=self.cwd,
        )
        thread = threading.Thread(target=self._pump_stderr, daemon=True)
        thread.start()

    def send_request(self, request_dict: Dict[str, Any]) -> Dict[str, Any]:
        """Sends a JSON-RPC request to stdin and reads the JSON-RPC response from stdout."""
        if not self.process or self.process.poll() is not None:
            stderr = "".join(self._stderr_tail)
            raise RuntimeError(f"MCP Stdio transport process is not running. Stderr: {stderr}")

        msg_str = json.dumps(request_dict) + "\n"
        with self._lock:
            self.process.stdin.write(msg_str)
            self.process.stdin.flush()
            if request_dict.get("id") is None:
                return {}
            return self._read_message()

    def close(self) -> None:
        """Terminates the MCP server subprocess cleanly."""
        if self.process:
            try:
                self.process.terminate()
                self.process.wait(timeout=2)
            except Exception:
                if self.process.poll() is None:
                    self.process.kill()
            finally:
                self.process = None

    def _read_message(self) -> Dict[str, Any]:
        stdout = self.process.stdout if self.process else None
        if stdout is None:
            raise RuntimeError("MCP Stdio transport process is not running.")

        headers: Dict[str, str] = {}
        while True:
            line = stdout.readline()
            if not line:
                stderr = "".join(self._stderr_tail)
                raise RuntimeError(f"MCP server closed stdout unexpectedly. Stderr: {stderr}")
            if line in ("\n", "\r\n"):
                break
            stripped = line.strip()
            if stripped.startswith("{") and "content-length" not in headers:
                return parse_json_rpc(stripped)
            if ":" in stripped:
                key, value = stripped.split(":", 1)
                headers[key.strip().lower()] = value.strip()

        if "content-length" not in headers:
            stderr = "".join(self._stderr_tail)
            raise RuntimeError(f"MCP server sent a message without Content-Length. Stderr: {stderr}")
        length = int(headers["content-length"])
        body = stdout.read(length)
        if len(body) != length:
            stderr = "".join(self._stderr_tail)
            raise RuntimeError(f"MCP server closed stdout mid-message. Stderr: {stderr}")
        return parse_json_rpc(body)

    def _pump_stderr(self) -> None:
        process = self.process
        if not process or not process.stderr:
            return
        try:
            for line in process.stderr:
                self._stderr_tail.append(line)
        except Exception:
            return
