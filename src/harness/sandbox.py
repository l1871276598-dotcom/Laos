import hashlib
import os
import platform
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Dict, List, Optional, Union

from .types import SandboxResult


class SandboxTimeoutError(Exception):
    """Raised when a command running inside a sandbox exceeds its execution timeout."""
    pass


class SandboxExecutionError(Exception):
    """Raised when a sandbox fails during creation or configuration."""
    pass


class EphemeralSandbox:
    """An ephemeral, isolated execution environment with automatic lifecycle cleanup."""

    def __init__(self, prefix: str = "laos-sb-"):
        self.prefix = prefix
        self._temp_dir: Optional[tempfile.TemporaryDirectory] = None
        self.path: Optional[Path] = None

    def __enter__(self) -> "EphemeralSandbox":
        self._temp_dir = tempfile.TemporaryDirectory(prefix=self.prefix)
        self.path = Path(self._temp_dir.name)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.cleanup()

    def cleanup(self) -> None:
        """Force destruction of sandbox directory."""
        if self._temp_dir is not None:
            try:
                self._temp_dir.cleanup()
            finally:
                self._temp_dir = None
                self.path = None

    @staticmethod
    def get_env_fingerprint() -> str:
        ident = f"{platform.platform()}:{platform.python_version()}:{platform.machine()}"
        return hashlib.sha256(ident.encode("utf-8")).hexdigest()

    def run_command(
        self,
        cmd: Union[List[str], str],
        timeout: Optional[float] = 30.0,
        env: Optional[Dict[str, str]] = None,
    ) -> SandboxResult:
        """Execute a command inside the sandbox workspace, capturing exit code and output hashes."""
        if not self.path or not self.path.exists():
            raise SandboxExecutionError("Sandbox environment is not initialized or has been destroyed.")

        run_env = os.environ.copy()
        if env:
            run_env.update(env)

        start_ns = time.monotonic_ns()
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(self.path),
                capture_output=True,
                text=True,
                timeout=timeout,
                env=run_env,
                shell=isinstance(cmd, str),
            )
            duration_ms = (time.monotonic_ns() - start_ns) // 1_000_000
            stdout_str = proc.stdout
            stderr_str = proc.stderr
            out_sha = hashlib.sha256(stdout_str.encode("utf-8")).hexdigest()
            err_sha = hashlib.sha256(stderr_str.encode("utf-8")).hexdigest()

            return SandboxResult(
                exit_code=proc.returncode,
                stdout=stdout_str,
                stderr=stderr_str,
                stdout_sha256=out_sha,
                stderr_sha256=err_sha,
                duration_ms=duration_ms,
                environment_fingerprint=self.get_env_fingerprint(),
            )
        except subprocess.TimeoutExpired as e:
            raise SandboxTimeoutError(
                f"Command timed out after {timeout} seconds: {cmd}"
            ) from e


class WorktreeSandbox(EphemeralSandbox):
    """An ephemeral Git worktree sandbox based on an isolated detached HEAD."""

    def __init__(
        self,
        repo_root: Union[Path, str],
        commit_or_branch: str = "HEAD",
        prefix: str = "laos-wt-",
    ):
        super().__init__(prefix=prefix)
        self.repo_root = Path(repo_root).resolve()
        self.commit_or_branch = commit_or_branch
        self._raw_dir: Optional[tempfile.TemporaryDirectory] = None

    def __enter__(self) -> "WorktreeSandbox":
        self._raw_dir = tempfile.TemporaryDirectory(prefix=self.prefix)
        self.path = Path(self._raw_dir.name) / "worktree"
        try:
            subprocess.run(
                ["git", "worktree", "add", "--detach", str(self.path), self.commit_or_branch],
                cwd=str(self.repo_root),
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError as e:
            self.cleanup()
            raise SandboxExecutionError(
                f"Failed to create git worktree at {self.path}: {e.stderr}"
            ) from e
        return self

    def cleanup(self) -> None:
        """Safely destroy worktree and prune Git worktree registry."""
        if self.path and self.path.exists():
            try:
                subprocess.run(
                    ["git", "worktree", "remove", "--force", str(self.path)],
                    cwd=str(self.repo_root),
                    capture_output=True,
                    text=True,
                )
                subprocess.run(
                    ["git", "worktree", "prune"],
                    cwd=str(self.repo_root),
                    capture_output=True,
                    text=True,
                )
            except Exception:
                pass

        if self._raw_dir is not None:
            try:
                self._raw_dir.cleanup()
            finally:
                self._raw_dir = None
                self.path = None
