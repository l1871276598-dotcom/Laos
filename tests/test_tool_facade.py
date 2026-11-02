import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from tool_facade import LaosToolFacade


class Application:
    def __init__(self, results=None):
        self.tasks = []
        self.results = results or []

    def run(self, task):
        self.tasks.append(task)
        return {"task": task, "output": {"results": self.results}}


class Sessions:
    def list(self, **kwargs):
        return [kwargs]

    def get(self, session_id):
        return {"id": session_id}

    def search(self, query, **kwargs):
        return [{"query": query, **kwargs}]


class Proposals:
    def list(self, status):
        return [{"status": status}]

    def review(self, proposal_id, action, reason):
        return {"proposal_id": proposal_id, "action": action, "reason": reason}


class Manager:
    def apply(self, proposal_id):
        return {"applied": proposal_id}

    def rollback(self, proposal_id):
        return {"rolled_back": proposal_id}


class CheckpointCapture:
    def capture(self, **values):
        return {"captured": values}


class Optimizer:
    def optimize(self, procedure_id_or_path, workspace="personal", dry_run=False, evaluator_models=None):
        return {
            "procedure_id": procedure_id_or_path,
            "workspace": workspace,
            "dry_run": dry_run,
            "evaluator_models": evaluator_models,
            "status": "candidate_created",
        }


class ToolFacadeTests(unittest.TestCase):
    def test_routes_to_native_services(self):
        facade = LaosToolFacade(
            Application(),
            Sessions(),
            Proposals(),
            Manager(),
            CheckpointCapture(),
        )
        self.assertEqual(facade.run_task({"type": "memory.search"})["task"]["type"], "memory.search")
        self.assertEqual(
            facade.capture_checkpoint(session_alias="one")["captured"]["session_alias"],
            "one",
        )
        self.assertEqual(facade.session_get("one")["id"], "one")
        self.assertEqual(facade.session_search("PDC")[0]["query"], "PDC")
        self.assertEqual(facade.procedure_list()[0]["status"], "candidate")
        self.assertEqual(facade.procedure_apply("p")["applied"], "p")
        self.assertEqual(facade.procedure_rollback("p")["rolled_back"], "p")

    def test_memory_search_is_scoped_bounded_and_read_only(self):
        application = Application([{"id": str(index)} for index in range(60)])
        facade = LaosToolFacade(application)

        rows = facade.memory_search("最少代码", "personal", "project-one", 2)

        self.assertEqual(rows, [{"id": "0"}, {"id": "1"}])
        self.assertEqual(
            application.tasks,
            [
                {
                    "type": "memory.search",
                    "input": {
                        "query": "最少代码",
                        "workspace": "personal",
                        "project": "project-one",
                    },
                }
            ],
        )
        for values in [
            ("", "personal", None, 20),
            ("query", "invalid", None, 20),
            ("query", "personal", "", 20),
            ("query", "personal", None, 0),
            ("query", "personal", None, 51),
            ("query", "personal", None, True),
        ]:
            with self.subTest(values=values), self.assertRaises(ValueError):
                facade.memory_search(*values)
        self.assertEqual(len(application.tasks), 1)

    def test_memory_search_rejects_malformed_application_output(self):
        class MalformedApplication:
            def run(self, task):
                return {"output": {}}

        with self.assertRaises(RuntimeError):
            LaosToolFacade(MalformedApplication()).memory_search("query", "personal")

    def test_missing_service_fails_closed(self):
        facade = LaosToolFacade(Application())
        with self.assertRaises(RuntimeError):
            facade.capture_checkpoint(session_alias="one")
        with self.assertRaises(RuntimeError):
            facade.session_get("one")
        with self.assertRaises(RuntimeError):
            facade.procedure_list()

    def test_context_build_routes_and_validates(self):
        import tempfile
        class CtxApp:
            def __init__(self):
                self.tasks = []
            def run(self, task):
                self.tasks.append(task)
                return {"output": {"text": "context_text", "sources": ["s1"], "used": 100}}

        with tempfile.TemporaryDirectory() as td:
            ledger_file = Path(td) / "tokens.jsonl"
            app = CtxApp()
            facade = LaosToolFacade(app, token_ledger_path=ledger_file)
            res = facade.context_build("query", "personal", project="p1", limit=4000)
            self.assertEqual(res["text"], "context_text")
            self.assertEqual(app.tasks[0]["type"], "context.build")
            self.assertEqual(app.tasks[0]["workspace"], "personal")
            self.assertEqual(app.tasks[0]["input"]["query"], "query")

            summary = facade.token_summary()
            self.assertEqual(summary["total_records"], 1)
            self.assertEqual(summary["total_prompt_tokens"], 100)

        with self.assertRaises(ValueError):
            facade.context_build("", "personal")
        with self.assertRaises(ValueError):
            facade.context_build("q", "invalid_ws")
        with self.assertRaises(ValueError):
            facade.context_build("q", "personal", limit=-1)

    def test_memory_create_candidate_routes(self):
        class CandApp:
            def __init__(self):
                self.tasks = []
            def run(self, task):
                self.tasks.append(task)
                return {"output": {"candidate_id": "cand-123", "status": "candidate"}}

        app = CandApp()
        facade = LaosToolFacade(app)
        res = facade.memory_create_candidate(
            title="Always Test",
            content="Testing is good",
            workspace="personal",
            tags=["tdd", "code"],
        )
        self.assertEqual(res["candidate_id"], "cand-123")
        self.assertEqual(app.tasks[0]["type"], "memory.create")
        self.assertEqual(app.tasks[0]["input"]["title"], "Always Test")
        self.assertEqual(app.tasks[0]["input"]["action"], "create")

    def test_health_token_summary_and_patterns(self):
        class MockHealth:
            def run(self):
                return {"healthy": True, "mock": True}

        facade = LaosToolFacade(
            Application(),
            health_check=MockHealth(),
            token_ledger_path="/nonexistent/tokens.jsonl",
        )
        self.assertTrue(facade.health()["healthy"])
        summary = facade.token_summary()
        self.assertEqual(summary["total_records"], 0)
        self.assertEqual(summary["total_cost_usd"], 0.0)
        patterns = facade.pattern_list()
        self.assertEqual(patterns, [])

    def test_procedure_optimize_routes_and_validates(self):
        facade = LaosToolFacade(
            Application(),
            optimizer=Optimizer(),
        )
        res = facade.procedure_optimize(
            "procedure-123",
            workspace="personal",
            dry_run=True,
            evaluator_models=["gpt-4o", "claude-3-5-sonnet"],
        )
        self.assertEqual(res["procedure_id"], "procedure-123")
        self.assertEqual(res["workspace"], "personal")
        self.assertTrue(res["dry_run"])
        self.assertEqual(res["evaluator_models"], ["gpt-4o", "claude-3-5-sonnet"])

        # Input validations
        with self.assertRaises(ValueError):
            facade.procedure_optimize("", "personal")
        with self.assertRaises(ValueError):
            facade.procedure_optimize("p1", "invalid_workspace")
        with self.assertRaises(ValueError):
            facade.procedure_optimize("p1", "personal", dry_run="not_a_bool")
        with self.assertRaises(ValueError):
            facade.procedure_optimize("p1", "personal", evaluator_models="not_a_list")
        with self.assertRaises(ValueError):
            facade.procedure_optimize("p1", "personal", evaluator_models=[""])

        # Unavailable optimizer
        empty_facade = LaosToolFacade(Application())
        with self.assertRaises(RuntimeError):
            empty_facade.procedure_optimize("p1", "personal")



if __name__ == "__main__":
    unittest.main()
