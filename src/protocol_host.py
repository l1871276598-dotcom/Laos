from __future__ import annotations


def build_protocol_host(facade, *, server_options=None):
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:
        raise ImportError("optional MCP SDK is required") from exc

    checkpoint_enabled = getattr(facade, "checkpoint_capture", None) is not None
    instructions = "Read and update LAOS only through reviewed native operations."
    if checkpoint_enabled:
        instructions += (
            " The checkpoint tool is explicit, not passive: call it only when the "
            "current user message and the exact completed assistant response are available."
        )
    host = FastMCP("laos", instructions=instructions, **dict(server_options or {}))

    @host.tool()
    def laos_task(task: dict) -> dict:
        return facade.run_task(task)

    @host.tool()
    def laos_memory_search(
        query: str,
        workspace: str,
        project: str | None = None,
        limit: int = 20,
    ) -> list[dict]:
        """Run a read-only search against the configured LAOS data root.

        The tool searches active visible memories and indexed documents only. It
        does not accept filesystem paths, database paths, write flags, or shell
        commands. `workspace` must be `personal` or `work`; `limit` is capped at 50.
        """
        return facade.memory_search(query, workspace, project, limit)

    @host.tool()
    def laos_handoff_write(
        project_slug: str,
        content: str,
        workspace: str,
        expected_sha256: str | None = None,
    ) -> dict:
        """Write one project handoff through the LAOS handoff gate.

        `project_slug` must name an active source-backed project. The tool writes
        through staging and publishes only to `projects/<project_slug>/handoff.md`.
        It does not write or overwrite root-level legacy handoff files.
        """
        return facade.handoff_write(project_slug, content, workspace=workspace, expected_sha256=expected_sha256)

    if checkpoint_enabled:

        @host.tool()
        def laos_capture_checkpoint(
            session_alias: str,
            user_message: str,
            assistant_response: str,
            checkpoint_id: str | None = None,
            conversation_summary: str | None = None,
            assistant_response_complete: bool = True,
            source_conversation_id: str | None = None,
            source_user_message_id: str | None = None,
            source_assistant_message_id: str | None = None,
            branch_id: str = "main",
            version: int = 1,
            captured_at: str | None = None,
            force_review: bool = False,
        ) -> dict:
            """Explicitly save one completed ChatGPT exchange into LAOS.

            This tool cannot inspect the conversation automatically. `user_message`
            must be the current user message and `assistant_response` must exactly
            match the completed response that will be shown to the user. Keep
            `session_alias` stable across one conversation. Supply source IDs only
            when the host exposes real stable IDs; never invent them. Reuse a stable
            `checkpoint_id` when retrying the same exchange. Set `force_review` only
            when immediate Memory and Procedure candidate review is required.
            """
            return facade.capture_checkpoint(
                session_alias=session_alias,
                user_message=user_message,
                assistant_response=assistant_response,
                checkpoint_id=checkpoint_id,
                conversation_summary=conversation_summary,
                assistant_response_complete=assistant_response_complete,
                source_conversation_id=source_conversation_id,
                source_user_message_id=source_user_message_id,
                source_assistant_message_id=source_assistant_message_id,
                branch_id=branch_id,
                version=version,
                captured_at=captured_at,
                force_review=force_review,
            )

    @host.tool()
    def laos_session_search(
        query: str,
        workspace: str | None = None,
        project: str | None = None,
        limit: int = 20,
    ) -> list[dict]:
        return facade.session_search(query, workspace, project, limit)

    @host.tool()
    def laos_session_get(session_id: str) -> dict:
        return facade.session_get(session_id)

    @host.tool()
    def laos_procedure_list(status: str = "candidate") -> list[dict]:
        """List procedure proposals filtered by status ('candidate', 'approved', 'rejected')."""
        return facade.procedure_list(status)

    @host.tool()
    def laos_procedure_review(
        proposal_id: str,
        action: str,
        reason: str | None = None,
    ) -> dict:
        """Review a candidate procedure proposal, approving or rejecting it.

        `action` must be 'approved' or 'rejected'.
        """
        return facade.procedure_review(proposal_id, action, reason)

    @host.tool()
    def laos_procedure_apply(proposal_id: str) -> dict:
        """Apply an approved procedure proposal into the active system procedures."""
        return facade.procedure_apply(proposal_id)

    @host.tool()
    def laos_procedure_rollback(proposal_id: str) -> dict:
        """Roll back an applied procedure proposal."""
        return facade.procedure_rollback(proposal_id)

    @host.tool()
    def laos_context_build(
        query: str,
        workspace: str,
        project: str | None = None,
        limit: int = 8000,
    ) -> dict:
        """Assemble prompt context from active memories and heuristic patterns under token budget.

        Returns text, sources, limit, and used token/character counters.
        `workspace` must be 'personal' or 'work'.
        """
        return facade.context_build(query, workspace, project=project, limit=limit)

    @host.tool()
    def laos_memory_create_candidate(
        title: str,
        content: str,
        workspace: str,
        type: str = "principle",
        scope: str = "global",
        confidentiality: str = "personal",
        project: str | None = None,
        tags: list[str] | None = None,
        confidence: str = "provisional",
        source: str = "agent-mcp",
    ) -> dict:
        """Propose a new memory candidate (principle, decision, guideline) into LAOS staging.

        Requires human or gate review before activation into long-term authority.
        `workspace` must be 'personal' or 'work'.
        """
        return facade.memory_create_candidate(
            title=title,
            content=content,
            workspace=workspace,
            type=type,
            scope=scope,
            confidentiality=confidentiality,
            project=project,
            tags=tags,
            confidence=confidence,
            source=source,
        )

    @host.tool()
    def laos_health() -> dict:
        """Check LAOS backend health, index status, and directory permissions."""
        return facade.health()

    @host.tool()
    def laos_token_summary() -> dict:
        """Get the Token usage and financial expenditure summary across models."""
        return facade.token_summary()

    @host.tool()
    def laos_pattern_feedback(
        pattern_id: str,
        outcome: str,
        reason: str | None = None,
    ) -> dict:
        """Record execution feedback (PASS/FAIL) for a learned heuristic pattern.

        Updates confidence and PageRank authority ranking deterministically.
        """
        return facade.pattern_feedback(pattern_id, outcome, reason=reason)

    @host.tool()
    def laos_pattern_list(
        keywords: list[str] | None = None,
        top_k: int = 10,
        min_confidence: float = 0.5,
    ) -> list[dict]:
        """List top learned heuristic patterns ranked by PageRank, confidence, and keyword match."""
        return facade.pattern_list(
            keywords=keywords, top_k=top_k, min_confidence=min_confidence
        )

    return host
