import hashlib
import platform
import subprocess
import time
from typing import List, Optional, Union

from .types import PhysicalWitness, SandboxResult


class TruthProbe:
    """Step 5 Truth Probing client that produces untamperable PhysicalWitness instances."""

    @staticmethod
    def get_env_fingerprint() -> str:
        ident = f"{platform.platform()}:{platform.python_version()}:{platform.machine()}"
        return hashlib.sha256(ident.encode("utf-8")).hexdigest()

    def mint_witness_from_sandbox_result(
        self,
        pipeline_id: str,
        step_id: str,
        sandbox_result: SandboxResult,
    ) -> PhysicalWitness:
        return PhysicalWitness(
            pipeline_id=pipeline_id,
            step_id=step_id,
            exit_code=sandbox_result.exit_code,
            stdout_sha256=sandbox_result.stdout_sha256,
            stderr_sha256=sandbox_result.stderr_sha256,
            wall_clock_duration_ms=sandbox_result.duration_ms,
            environment_fingerprint=sandbox_result.environment_fingerprint or self.get_env_fingerprint(),
            is_valid=(sandbox_result.exit_code == 0),
        )

    def execute_probe(
        self,
        pipeline_id: str,
        step_id: str,
        probe_command: Union[List[str], str],
        timeout: float = 10.0,
        cwd: Optional[str] = None,
    ) -> PhysicalWitness:
        start_ns = time.monotonic_ns()
        try:
            proc = subprocess.run(
                probe_command,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=timeout,
                shell=isinstance(probe_command, str),
            )
            duration_ms = (time.monotonic_ns() - start_ns) // 1_000_000
            out_sha = hashlib.sha256(proc.stdout.encode("utf-8")).hexdigest()
            err_sha = hashlib.sha256(proc.stderr.encode("utf-8")).hexdigest()
            return PhysicalWitness(
                pipeline_id=pipeline_id,
                step_id=step_id,
                exit_code=proc.returncode,
                stdout_sha256=out_sha,
                stderr_sha256=err_sha,
                wall_clock_duration_ms=duration_ms,
                environment_fingerprint=self.get_env_fingerprint(),
                is_valid=(proc.returncode == 0),
            )
        except subprocess.TimeoutExpired:
            duration_ms = (time.monotonic_ns() - start_ns) // 1_000_000
            return PhysicalWitness(
                pipeline_id=pipeline_id,
                step_id=step_id,
                exit_code=-1,
                stdout_sha256="",
                stderr_sha256=hashlib.sha256(b"probe_timed_out").hexdigest(),
                wall_clock_duration_ms=duration_ms,
                environment_fingerprint=self.get_env_fingerprint(),
                is_valid=False,
            )
