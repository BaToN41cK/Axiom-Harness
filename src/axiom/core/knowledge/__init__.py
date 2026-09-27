"""Knowledge Base (RAG v1) — local document indexing and cited retrieval (W2.2).

Collections of local folders/files are chunked into an SQLite/FTS5 store
(BM25 ranking works fully offline). Ollama embeddings are an optional
re-ranking layer; when unavailable the index stays usable and the store
reports an honest ``embeddings`` status instead of pretending to be vector
search. Only changed files are re-indexed (mtime + size fingerprint).
"""

from axiom.core.knowledge.manager import KnowledgeManager
from axiom.core.knowledge.store import Embedder, KnowledgeHit, KnowledgeStore
from axiom.core.knowledge.tools import (
    KNOWLEDGE_INDEX_TOOL,
    KNOWLEDGE_SEARCH_TOOL,
    KNOWLEDGE_STATUS_TOOL,
    KnowledgeTools,
)

__all__ = [
    "KNOWLEDGE_INDEX_TOOL",
    "KNOWLEDGE_SEARCH_TOOL",
    "KNOWLEDGE_STATUS_TOOL",
    "Embedder",
    "KnowledgeHit",
    "KnowledgeManager",
    "KnowledgeStore",
    "KnowledgeTools",
]
