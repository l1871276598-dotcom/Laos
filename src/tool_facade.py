class LaosToolFacade:
    def __init__(
        self,
        application,
        sessions=None,
        procedures=None,
        manager=None,
        checkpoint_capture=None,
        health_check=None,
        token_ledger_path=None,
        pattern_graph_path=None,
    ):
        self.application = application
        self.sessions = sessions
        self.procedures = procedures
        self.manager = manager
        self.checkpoint_capture = checkpoint_capture
        self.health_check = health_check
        self.token_ledger_path = token_ledger_path
        self.pattern_graph_path = pattern_graph_path

    def run_task(self, task):
        return self.application.run(task)

    def memory_search(self, query, workspace, project=None, limit=20):
        if not isinstance(query, str) or not query.strip():
            raise ValueError("query must be a non-empty string")
        if workspace not in {"personal", "work"}:
            raise ValueError("workspace must be personal or work")
        if project is not None and (not isinstance(project, str) or not project.strip()):
            raise ValueError("project must be a non-empty string")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 50:
            raise ValueError("limit must be between 1 and 50")

        values = {"query": query, "workspace": workspace}
        if project is not None:
            values["project"] = project
        result = self.application.run({"type": "memory.search", "input": values})
        try:
            rows = result["output"]["results"]
        except (KeyError, TypeError) as exc:
            raise RuntimeError("memory search returned an invalid result") from exc
        if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
            raise RuntimeError("memory search returned an invalid result")
        return rows[:limit]

    def handoff_write(self, project_slug, content, *, workspace, expected_sha256=None):
        if not isinstance(project_slug, str) or not project_slug.strip():
            raise ValueError("project_slug must be a non-empty string")
        if not isinstance(content, str) or not content.strip():
            raise ValueError("content must be a non-empty string")
        if expected_sha256 is not None and (not isinstance(expected_sha256, str) or not expected_sha256.strip()):
            raise ValueError("expected_sha256 must be a non-empty string")
        if workspace not in {"personal", "work"}:
            raise ValueError("workspace must be personal or work")

        values = {"project_slug": project_slug, "content": content}
        if expected_sha256 is not None:
            values["expected_sha256"] = expected_sha256
        result = self.application.run(
            {"type": "handoff.write", "workspace": workspace, "input": values}
        )
        try:
            output = result["output"]
        except (KeyError, TypeError) as exc:
            raise RuntimeError("handoff write returned an invalid result") from exc
        if not isinstance(output, dict) or output.get("project_slug") != project_slug:
            raise RuntimeError("handoff write returned an invalid result")
        return output

    def capture_checkpoint(self, **values):
        if self.checkpoint_capture is None:
            raise RuntimeError("MCP checkpoint capture is unavailable")
        return self.checkpoint_capture.capture(**values)

    def session_list(self, workspace=None, project=None, limit=50):
        if self.sessions is None:
            raise RuntimeError("session store is unavailable")
        return self.sessions.list(workspace=workspace, project=project, limit=limit)

    def session_get(self, session_id):
        if self.sessions is None:
            raise RuntimeError("session store is unavailable")
        return self.sessions.get(session_id)

    def session_search(self, query, workspace=None, project=None, limit=20):
        if self.sessions is None:
            raise RuntimeError("session store is unavailable")
        return self.sessions.search(
            query,
            workspace=workspace,
            project=project,
            limit=limit,
        )

    def procedure_list(self, status="candidate"):
        if self.procedures is None:
            raise RuntimeError("procedure proposal store is unavailable")
        return self.procedures.list(status)

    def procedure_review(self, proposal_id, action, reason=None):
        if self.procedures is None:
            raise RuntimeError("procedure proposal store is unavailable")
        return self.procedures.review(proposal_id, action, reason)

    def procedure_apply(self, proposal_id):
        if self.manager is None:
            raise RuntimeError("procedure manager is unavailable")
        return self.manager.apply(proposal_id)

    def procedure_rollback(self, proposal_id):
        if self.manager is None:
            raise RuntimeError("procedure manager is unavailable")
        return self.manager.rollback(proposal_id)

    def context_build(self, query, workspace, project=None, limit=8000):
        if not isinstance(query, str) or not query.strip():
            raise ValueError("query must be a non-empty string")
        if workspace not in {"personal", "work"}:
            raise ValueError("workspace must be personal or work")
        if project is not None and (not isinstance(project, str) or not project.strip()):
            raise ValueError("project must be a non-empty string")
        if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
            raise ValueError("limit must be a positive integer")

        values = {"query": query, "workspace": workspace, "limit": limit}
        if project is not None:
            values["project"] = project
        result = self.application.run(
            {"type": "context.build", "workspace": workspace, "input": values}
        )
        try:
            return result["output"]
        except (KeyError, TypeError) as exc:
            raise RuntimeError("context build returned an invalid result") from exc

    def memory_create_candidate(
        self,
        title,
        content,
        workspace,
        type="principle",
        scope="global",
        confidentiality="personal",
        project=None,
        tags=None,
        confidence="provisional",
        source="agent-mcp",
    ):
        if not isinstance(title, str) or not title.strip():
            raise ValueError("title must be a non-empty string")
        if not isinstance(content, str) or not content.strip():
            raise ValueError("content must be a non-empty string")
        if workspace not in {"personal", "work"}:
            raise ValueError("workspace must be personal or work")

        candidate = {
            "type": type,
            "title": title.strip(),
            "content": content.strip(),
            "workspace": workspace,
            "scope": scope,
            "confidentiality": confidentiality,
            "confidence": confidence,
            "source": source,
            "action": "create",
        }
        if project is not None:
            candidate["project"] = project
        if tags is not None:
            candidate["tags"] = list(tags)

        result = self.application.run(
            {"type": "memory.create", "workspace": workspace, "input": candidate}
        )
        try:
            return result["output"]
        except (KeyError, TypeError) as exc:
            raise RuntimeError("memory create returned an invalid result") from exc

    def health(self):
        if self.health_check is not None:
            return self.health_check.run()
        return {"healthy": True, "checks": []}

    def token_summary(self):
        try:
            from src.models.router import TokenLedger
        except ImportError:
            from models.router import TokenLedger

        if self.token_ledger_path is not None:
            return TokenLedger.summarize_file(self.token_ledger_path)
        return {
            "total_records": 0,
            "total_prompt_tokens": 0,
            "total_completion_tokens": 0,
            "total_cache_read_tokens": 0,
            "total_cost_usd": 0.0,
            "models": {},
        }

    def pattern_list(self, keywords=None, top_k=10, min_confidence=0.5):
        from pathlib import Path
        import json
        try:
            from src.learning_loop.pattern_engine import (
                PatternGraph,
                deserialize_graph,
                get_top_hints,
            )
        except ImportError:
            from learning_loop.pattern_engine import (
                PatternGraph,
                deserialize_graph,
                get_top_hints,
            )

        graph = PatternGraph()
        if self.pattern_graph_path and Path(self.pattern_graph_path).is_file():
            try:
                data = json.loads(
                    Path(self.pattern_graph_path).read_text(encoding="utf-8")
                )
                graph = deserialize_graph(data)
            except Exception:
                pass
        return get_top_hints(
            graph,
            query_keywords=keywords,
            top_k=top_k,
            min_confidence=min_confidence,
        )

    def pattern_feedback(self, pattern_id, outcome, reason=None):
        from pathlib import Path
        import json
        import time
        try:
            from src.learning_loop.pattern_engine import (
                PatternGraph,
                deserialize_graph,
                serialize_graph,
                apply_outcome,
            )
        except ImportError:
            from learning_loop.pattern_engine import (
                PatternGraph,
                deserialize_graph,
                serialize_graph,
                apply_outcome,
            )

        if not self.pattern_graph_path:
            raise RuntimeError("pattern graph path is not configured")
        path = Path(self.pattern_graph_path)
        graph = PatternGraph()
        if path.is_file():
            data = json.loads(path.read_text(encoding="utf-8"))
            graph = deserialize_graph(data)
        updated = apply_outcome(graph, pattern_id, outcome, now_epoch=int(time.time()))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(serialize_graph(graph), indent=2), encoding="utf-8")
        result = updated.to_dict()
        if reason:
            result["feedback_reason"] = reason
        return result

