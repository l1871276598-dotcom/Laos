import ast
import os
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = REPO_ROOT / "src"
HARNESS_DIR = SOURCE_DIR / "harness"


class TestArchitectureGuards(unittest.TestCase):
    """Enforces Khazix & Karpathy architectural invariants via static AST analysis."""

    def test_kernel_zero_network_imports(self):
        """Kernel must have ZERO network I/O imports; network operations belong only in adapters."""
        forbidden_modules = {
            "urllib",
            "requests",
            "aiohttp",
            "socket",
            "http",
            "httpx",
            "urllib3",
            "ftplib",
            "asyncio",  # keep kernel synchronous & deterministic
        }

        harness_files = list(HARNESS_DIR.glob("*.py"))
        self.assertGreater(len(harness_files), 0, "Harness files must exist")

        violations = []
        for py_file in harness_files:
            with open(py_file, "r", encoding="utf-8") as f:
                tree = ast.parse(f.read(), filename=str(py_file))

            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        top_pkg = alias.name.split(".")[0]
                        if top_pkg in forbidden_modules:
                            violations.append(f"{py_file.name}:{node.lineno} imports '{alias.name}'")
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        top_pkg = node.module.split(".")[0]
                        if top_pkg in forbidden_modules:
                            violations.append(f"{py_file.name}:{node.lineno} from '{node.module}'")

        self.assertEqual(
            violations,
            [],
            f"Zero-network invariant violated in kernel: {violations}",
        )

    def test_kernel_zero_vendor_hardcoding(self):
        """Kernel must not hardcode commercial vendor model names (use abstract adapters)."""
        forbidden_vendors = [
            "gpt-4",
            "gpt-3.5",
            "claude-3",
            "claude-2",
            "deepseek-coder",
            "gemini-1.5",
            "gemini-pro",
        ]

        harness_files = list(HARNESS_DIR.glob("*.py"))
        violations = []
        for py_file in harness_files:
            with open(py_file, "r", encoding="utf-8") as f:
                content = f.read().lower()
            for vendor in forbidden_vendors:
                if vendor in content:
                    violations.append(f"{py_file.name} contains '{vendor}'")

        self.assertEqual(
            violations,
            [],
            f"Vendor name hardcoding invariant violated: {violations}",
        )

    def test_kernel_loc_under_limit(self):
        """Kernel must remain minimal and transparent (< 1600 total lines of code)."""
        harness_files = list(HARNESS_DIR.glob("*.py"))
        total_loc = 0
        for py_file in harness_files:
            with open(py_file, "r", encoding="utf-8") as f:
                lines = f.readlines()
                total_loc += len(lines)

        self.assertLess(
            total_loc,
            1600,
            f"Harness kernel LOC ({total_loc}) exceeds the 1600 LOC ceiling.",
        )


if __name__ == "__main__":
    unittest.main()
