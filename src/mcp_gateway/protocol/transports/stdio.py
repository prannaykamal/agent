import json
import subprocess
import threading
from typing import Dict, Any, List, Optional
from src.mcp_gateway.protocol.json_rpc import parse_json_rpc

class StdioMCPTransport:
    """
    Stdio Subprocess Transport Adapter for MCP Servers.
    Launches server subprocess and communicates via standard stdin/stdout streams.
    """
    def __init__(self, command: str, args: Optional[List[str]] = None, env: Optional[Dict[str, str]] = None, cwd: Optional[str] = None):
        self.command = command
        self.args = args or []
        self.env = env
        self.cwd = cwd
        self.process: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()

    def connect(self) -> None:
        """Launches the external MCP server subprocess."""
        cmd_list = [self.command] + self.args
        self.process = subprocess.Popen(
            cmd_list,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            env=self.env,
            cwd=self.cwd
        )

    def send_request(self, request_dict: Dict[str, Any]) -> Dict[str, Any]:
        """Sends a JSON-RPC request to stdin and reads the JSON-RPC response from stdout."""
        if not self.process or self.process.poll() is not None:
            raise RuntimeError("MCP Stdio transport process is not running.")

        msg_str = json.dumps(request_dict) + "\n"
        with self._lock:
            self.process.stdin.write(msg_str)
            self.process.stdin.flush()

            # Read response line from stdout
            line = self.process.stdout.readline()
            if not line:
                stderr = self.process.stderr.read() if self.process.stderr else ""
                raise RuntimeError(f"MCP server closed stdout unexpectedly. Stderr: {stderr}")

            return parse_json_rpc(line.strip())

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
