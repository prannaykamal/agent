import os
import shutil
import sys
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Sequence, Tuple


def extra_bin_dirs() -> List[str]:
    """Return common executable dirs that GUI/API processes often omit from PATH."""
    dirs: List[str] = []
    exe = Path(sys.executable)
    dirs.append(str(exe.parent))
    resolved_parent = exe.resolve().parent
    if str(resolved_parent) != str(exe.parent):
        dirs.append(str(resolved_parent))
    virtual_env = os.environ.get("VIRTUAL_ENV")
    if virtual_env:
        dirs.append(str(Path(virtual_env) / "bin"))
    home = Path.home()
    nvm_versions = home / ".nvm" / "versions" / "node"
    if nvm_versions.is_dir():
        for bin_dir in sorted(nvm_versions.glob("*/bin"), reverse=True):
            if bin_dir.is_dir():
                dirs.append(str(bin_dir))
    for candidate in (
        home / ".local" / "bin",
        home / ".cargo" / "bin",
        Path("/opt/homebrew/bin"),
        Path("/opt/homebrew/opt/node/bin"),
        Path("/usr/local/bin"),
    ):
        if candidate.is_dir():
            dirs.append(str(candidate))
    seen = set()
    ordered: List[str] = []
    for item in dirs:
        if item not in seen:
            seen.add(item)
            ordered.append(item)
    return ordered


def merge_stdio_env(provider_env: Optional[Mapping[str, str]] = None) -> Dict[str, str]:
    merged = {str(key): str(value) for key, value in os.environ.items() if value is not None}
    extras = extra_bin_dirs()
    inherited_path = merged.get("PATH", "")
    if provider_env:
        for key, value in provider_env.items():
            if value is None:
                continue
            merged[str(key)] = str(value)
        if "PATH" in provider_env:
            inherited_path = str(provider_env["PATH"] or "")
        else:
            inherited_path = merged.get("PATH", inherited_path)
    parts = [*extras]
    if inherited_path:
        parts.append(inherited_path)
    merged["PATH"] = os.pathsep.join(parts)
    return merged


def resolve_stdio_launch(
    command: str,
    args: Optional[Sequence[str]] = None,
    env: Optional[Mapping[str, str]] = None,
) -> Tuple[str, List[str], Dict[str, str]]:
    """Resolve npx/uvx/etc. to an executable and keep provider env on top of the process env."""
    launch_args = [str(item) for item in (args or [])]
    launch_env = merge_stdio_env(env)
    resolved = _which(command, launch_env.get("PATH", ""))
    if resolved:
        return resolved, launch_args, launch_env

    if command == "uvx":
        uv = _which("uv", launch_env.get("PATH", ""))
        if uv:
            return uv, ["tool", "run", *launch_args], launch_env

    if command == "npx":
        npm = _which("npm", launch_env.get("PATH", ""))
        if npm:
            cleaned = [item for item in launch_args if item not in {"-y", "--yes"}]
            return npm, ["exec", "--yes", "--", *cleaned], launch_env

    raise FileNotFoundError(
        f"MCP stdio command {command!r} was not found on PATH. "
        "Install the launcher or start the API from a shell that can resolve it."
    )


def _which(command: str, path: str) -> Optional[str]:
    if not command:
        return None
    if os.path.sep in command or (os.path.altsep and os.path.altsep in command):
        if os.path.isfile(command) and os.access(command, os.X_OK):
            return command
        return None
    return shutil.which(command, path=path or None)
