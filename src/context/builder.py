import re


_WHITESPACE = re.compile(r"\s+")


class ContextBuilder:
    def __init__(self, store, pattern_graph=None):
        if not callable(getattr(store, "active_relevant", None)):
            raise ValueError("context store is invalid")
        self.store = store
        self.pattern_graph = pattern_graph

    @staticmethod
    def _normalize(value):
        return _WHITESPACE.sub(" ", str(value)).strip()

    @classmethod
    def _render(cls, entry):
        if not isinstance(entry, dict):
            raise ValueError("context entry must be a mapping")
        memory_id = entry.get("id")
        if not isinstance(memory_id, str) or not memory_id.strip():
            raise ValueError("context entry id must be a non-empty string")
        body = [
            f"title: {cls._normalize(entry.get('title', ''))}",
            f"content: {cls._normalize(entry.get('content', ''))}",
        ]
        tags = entry.get("tags")
        if tags:
            body.append("tags: " + ", ".join(cls._normalize(tag) for tag in tags))
        return cls._normalize(memory_id), "\n".join(body)

    @staticmethod
    def empty(limit=8000):
        if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
            raise ValueError("context limit must be a positive integer")
        return {"text": "", "sources": [], "limit": limit, "used": 0}

    def build(self, query, limit=8000, workspace=None, project=None, confidentiality=None):
        if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
            raise ValueError("context limit must be a positive integer")
        if not isinstance(workspace, str) or not workspace.strip():
            raise ValueError("workspace must be a non-empty string")
        if confidentiality is not None:
            entries = self.store.active_relevant(query, workspace, project, confidentiality)
        else:
            entries = self.store.active_relevant(query, workspace, project)
        text = ""
        sources = []
        seen_ids = set()
        seen_pieces = set()
        for entry in entries:
            entry_id, body = self._render(entry)
            if entry_id in seen_ids or body in seen_pieces:
                continue
            piece = f"id: {entry_id}\n{body}"
            separator = "\n\n" if text else ""
            remaining = limit - len(text)
            if remaining <= len(separator):
                break
            fitted = piece[: remaining - len(separator)]
            if not fitted:
                break
            text += separator + fitted
            sources.append(entry_id)
            seen_ids.add(entry_id)
            seen_pieces.add(body)
            if len(fitted) < len(piece):
                break

        res = {
            "text": text,
            "sources": sources,
            "limit": limit,
            "used": len(text),
        }

        # S5.6 Adaptive Ephemeral Hints Delivery (ADR-007)
        if self.pattern_graph is not None:
            try:
                from ..learning_loop.pattern_engine import get_top_hints
            except ImportError:
                from learning_loop.pattern_engine import get_top_hints

            ephemeral_hints = []
            query_tokens = [t.lower() for t in self._normalize(query).split() if len(t) > 2]
            top_hints = get_top_hints(self.pattern_graph, query_keywords=query_tokens, top_k=3, min_confidence=0.5)
            if top_hints:
                ephemeral_hints = top_hints
                hint_lines = ["tactical hints (non-authority):"]
                for h in top_hints:
                    hint_lines.append(f"- [{h['name']}] (conf: {h['confidence']}): {h['description']}")
                hint_block = "\n".join(hint_lines)
                separator = "\n\n" if text else ""
                remaining = limit - len(text)
                if remaining > len(separator) + 20:
                    fitted_hint = hint_block[: remaining - len(separator)]
                    text += separator + fitted_hint
                    res["text"] = text
                    res["used"] = len(text)

            res["ephemeral_hints"] = ephemeral_hints

        return res
