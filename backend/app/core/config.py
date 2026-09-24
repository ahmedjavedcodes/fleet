from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: str = "development"
    debug: bool = True
    database_url: str = "postgresql+psycopg://fleet:fleet@localhost:5432/fleet"
    secret_key: str = "change-me"
    access_token_expire_minutes: int = 60
    upload_dir: str = "uploads"
    # frontend/'s dev server origin -- without this, every browser request
    # from the Next.js app is blocked before it reaches any route below,
    # surfacing as a generic "could not reach the server" network error.
    cors_origins: list[str] = ["http://localhost:3000"]

    # Agent-memory vector search (Pinecone_Migration_Hardened.md). Unset key =
    # memory runs Postgres-only (scope + keyword recall, no similarity).
    pinecone_api_key: str | None = None
    pinecone_index: str = "fleet-memory"
    pinecone_namespace: str = "agent-memory"
    pinecone_cloud: str = "aws"
    pinecone_region: str = "us-east-1"

    # Document RAG (hybrid-document-rag-pipeline.md). Hybrid dense+sparse
    # search needs a dotproduct index, so documents get their own index.
    pinecone_documents_index: str = "fleet-documents"
    documents_namespace: str = "rag_documents"
    rag_dense_model: str = "llama-text-embed-v2"
    rag_sparse_model: str = "pinecone-sparse-english-v0"
    rag_rerank_model: str = "bge-reranker-v2-m3"
    # Calibrated live on bge-reranker-v2-m3: correct passages 0.576-0.997,
    # wrong ones <= 0.010. The spec's 0.65 (for bge-reranker-base) would drop
    # a correct paraphrase match at 0.576.
    rag_rerank_threshold: float = 0.30
    rag_alpha: float = 0.5
    rag_candidate_k: int = 10
    rag_max_chunks: int = 3
    rag_max_summarized_tables: int = 15
    rag_max_upload_mb: int = 20
    # Table summarization LLM (Groq, OpenAI-compatible). Unset key = tables are
    # indexed as raw Markdown, which the spec already defines as the fallback.
    groq_api_key: str | None = None
    rag_summary_model: str = "openai/gpt-oss-20b"


@lru_cache
def get_settings() -> Settings:
    return Settings()
