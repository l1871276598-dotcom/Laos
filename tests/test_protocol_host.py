import sys
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from protocol_host import build_protocol_host


class FakeFastMCP:
    def __init__(self, name, instructions, **options):
        self.name = name
        self.instructions = instructions
        self.options = options
        self.tools = {}

    def tool(self):
        def decorator(function):
            self.tools[function.__name__] = function
            return function

        return decorator


class Facade:
    def __init__(self, checkpoint_enabled=True):
        self.checkpoint_capture = object() if checkpoint_enabled else None

    def run_task(self, task):
        return {"task": task}

    def memory_search(self, query, workspace, project=None, limit=20):
        return [
            {
                "query": query,
                "workspace": workspace,
                "project": project,
                "limit": limit,
            }
        ]

    def capture_checkpoint(self, **values):
        return {"captured": values}

    def session_search(self, query, workspace=None, project=None, limit=20):
        return []

    def session_get(self, session_id):
        return {"id": session_id}

    def procedure_list(self, status="candidate"):
        return []

    def procedure_review(self, proposal_id, action, reason=None):
        return {"proposal_id": proposal_id, "action": action, "reason": reason}

    def procedure_apply(self, proposal_id):
        return {"applied": proposal_id}

    def procedure_rollback(self, proposal_id):
        return {"rolled_back": proposal_id}

    def context_build(self, query, workspace, project=None, limit=8000):
        return {"text": f"context for {query}", "workspace": workspace, "limit": limit}

    def memory_create_candidate(self, **kwargs):
        return {"candidate": kwargs}

    def health(self):
        return {"healthy": True}

    def token_summary(self):
        return {"total_records": 10, "total_cost_usd": 0.05}

    def pattern_feedback(self, pattern_id, outcome, reason=None):
        return {"pattern_id": pattern_id, "outcome": outcome, "reason": reason}

    def pattern_list(self, keywords=None, top_k=10, min_confidence=0.5):
        return [{"pattern_id": "p1", "name": "test pattern"}]

    def handoff_write(self, project_slug, content, *, workspace, expected_sha256=None):
        return {
            "project_slug": project_slug,
            "workspace": workspace,
            "expected_sha256": expected_sha256,
            "status": "created",
        }


def mcp_modules():
    module = types.ModuleType("mcp.server.fastmcp")
    module.FastMCP = FakeFastMCP
    return {
        "mcp": types.ModuleType("mcp"),
        "mcp.server": types.ModuleType("mcp.server"),
        "mcp.server.fastmcp": module,
    }


class ProtocolHostTests(unittest.TestCase):
    def test_memory_search_tool_is_read_only_and_routes_scoped_arguments(self):
        with mock.patch.dict(sys.modules, mcp_modules()):
            host = build_protocol_host(Facade(checkpoint_enabled=False))

        self.assertIn("laos_memory_search", host.tools)
        tool = host.tools["laos_memory_search"]
        result = tool("最少代码", "personal", "project-one", 5)
        self.assertEqual(
            result,
            [
                {
                    "query": "最少代码",
                    "workspace": "personal",
                    "project": "project-one",
                    "limit": 5,
                }
            ],
        )
        self.assertIn("read-only", tool.__doc__)
        self.assertIn("configured LAOS data root", tool.__doc__)

    def test_checkpoint_tool_is_explicit_and_routes_all_evidence_fields(self):
        with mock.patch.dict(sys.modules, mcp_modules()):
            host = build_protocol_host(Facade())

        self.assertIn("explicit, not passive", host.instructions)
        self.assertIn("laos_capture_checkpoint", host.tools)
        tool = host.tools["laos_capture_checkpoint"]
        result = tool(
            session_alias="conversation-one",
            user_message="Question",
            assistant_response="Answer",
            checkpoint_id="checkpoint-one",
            source_conversation_id="source-conversation",
            source_user_message_id="source-user",
            source_assistant_message_id="source-assistant",
            force_review=True,
        )
        values = result["captured"]
        self.assertEqual(values["session_alias"], "conversation-one")
        self.assertEqual(values["assistant_response"], "Answer")
        self.assertEqual(values["checkpoint_id"], "checkpoint-one")
        self.assertEqual(values["source_conversation_id"], "source-conversation")
        self.assertTrue(values["force_review"])
        self.assertIn("cannot inspect the conversation automatically", tool.__doc__)

    def test_checkpoint_tool_is_absent_when_capture_is_disabled(self):
        with mock.patch.dict(sys.modules, mcp_modules()):
            host = build_protocol_host(Facade(checkpoint_enabled=False))

        self.assertNotIn("checkpoint", host.instructions)
        self.assertNotIn("laos_capture_checkpoint", host.tools)
        self.assertIn("laos_memory_search", host.tools)

    def test_remote_server_options_are_passed_to_fastmcp(self):
        options = {
            "host": "127.0.0.1",
            "port": 8766,
            "streamable_http_path": "/mcp",
            "json_response": True,
            "stateless_http": True,
        }
        with mock.patch.dict(sys.modules, mcp_modules()):
            host = build_protocol_host(Facade(), server_options=options)

        self.assertEqual(host.options, options)

    def test_all_new_mcp_tools_are_registered_and_delegate_properly(self):
        with mock.patch.dict(sys.modules, mcp_modules()):
            host = build_protocol_host(Facade(checkpoint_enabled=False))

        expected_tools = [
            "laos_task",
            "laos_memory_search",
            "laos_handoff_write",
            "laos_session_search",
            "laos_session_get",
            "laos_procedure_list",
            "laos_procedure_review",
            "laos_procedure_apply",
            "laos_procedure_rollback",
            "laos_context_build",
            "laos_memory_create_candidate",
            "laos_health",
            "laos_token_summary",
            "laos_pattern_feedback",
            "laos_pattern_list",
        ]
        for name in expected_tools:
            self.assertIn(name, host.tools, f"Tool {name} should be registered in FastMCP host")

        # Test context_build
        ctx_tool = host.tools["laos_context_build"]
        ctx_res = ctx_tool("search query", "personal", limit=5000)
        self.assertEqual(ctx_res["text"], "context for search query")
        self.assertEqual(ctx_res["limit"], 5000)

        # Test memory_create_candidate
        mem_tool = host.tools["laos_memory_create_candidate"]
        mem_res = mem_tool("Rule 1", "Always follow rules", "personal")
        self.assertEqual(mem_res["candidate"]["title"], "Rule 1")

        # Test procedure tools
        self.assertEqual(host.tools["laos_procedure_review"]("p1", "approved")["action"], "approved")
        self.assertEqual(host.tools["laos_procedure_apply"]("p1")["applied"], "p1")
        self.assertEqual(host.tools["laos_procedure_rollback"]("p1")["rolled_back"], "p1")

        # Test health & telemetry & pattern tools
        self.assertTrue(host.tools["laos_health"]()["healthy"])
        self.assertEqual(host.tools["laos_token_summary"]()["total_cost_usd"], 0.05)
        self.assertEqual(host.tools["laos_pattern_feedback"]("pat-1", "PASS")["outcome"], "PASS")
        self.assertEqual(len(host.tools["laos_pattern_list"]()), 1)



class HandoffToolContractTests(unittest.TestCase):
    def _host(self):
        with mock.patch.dict(sys.modules, mcp_modules()):
            return build_protocol_host(Facade())

    def test_handoff_tool_workspace_required_sha_optional(self):
        import inspect

        host = self._host()
        tool = host.tools["laos_handoff_write"]
        params = inspect.signature(tool).parameters
        self.assertIs(params["workspace"].default, inspect.Parameter.empty)
        self.assertIsNone(params["expected_sha256"].default)

    def test_handoff_tool_creates_without_expected_sha256(self):
        host = self._host()
        result = host.tools["laos_handoff_write"](
            project_slug="research-agent-memory",
            content="content",
            workspace="personal",
        )
        self.assertEqual(result["status"], "created")
        self.assertEqual(result["workspace"], "personal")
        self.assertIsNone(result["expected_sha256"])

    def test_handoff_tool_rejects_missing_workspace(self):
        host = self._host()
        with self.assertRaises(TypeError):
            host.tools["laos_handoff_write"](
                project_slug="research-agent-memory",
                content="content",
            )


if __name__ == "__main__":
    unittest.main()
