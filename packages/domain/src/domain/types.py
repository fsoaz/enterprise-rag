from __future__ import annotations

from enum import StrEnum


class Role(StrEnum):
    ADMIN = "admin"
    STEWARD = "steward"
    MEMBER = "member"
    VIEWER = "viewer"


class AclSubjectType(StrEnum):
    USER = "user"
    GROUP = "group"
    ROLE = "role"


class AclResourceType(StrEnum):
    COLLECTION = "collection"
    DOCUMENT = "document"


class AclPermission(StrEnum):
    READ = "read"
    WRITE = "write"
    MANAGE = "manage"


class AclEffect(StrEnum):
    ALLOW = "allow"
    DENY = "deny"


class GroundednessVerdict(StrEnum):
    GROUNDED = "grounded"
    PARTIAL = "partial"
    UNSUPPORTED = "unsupported"


class IngestionStage(StrEnum):
    DOWNLOAD = "download"
    PARSE = "parse"
    OCR = "ocr"
    CHUNK = "chunk"
    EMBED = "embed"
    INDEX = "index"


class JobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class TenantStatus(StrEnum):
    ACTIVE = "active"
    SUSPENDED = "suspended"


class UserStatus(StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"


class ParseStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class RetrievalStrategy(StrEnum):
    DENSE_ONLY = "dense_only"
    LEXICAL_ONLY = "lexical_only"
    HYBRID_RRF = "hybrid_rrf"
    HYBRID_RERANK = "hybrid_rerank"


EMBEDDING_DIM = 1024
DEFAULT_RRF_K = 60

# Chunks scoring at or above this are excluded from retrieval outright: the score
# only reaches this band on explicit instruction-override patterns ("ignore previous
# instructions", "reveal your instructions", chat-template markers), which are not
# things a genuine policy document says. Below it, a chunk is still retrievable but
# is marked untrusted for the generation prompt.
INJECTION_RISK_BLOCK = 0.8
INJECTION_RISK_FLAG = 0.5
DEFAULT_CHUNK_TOKENS = 512
DEFAULT_CHUNK_OVERLAP = 64
DEFAULT_TOP_K_RETRIEVAL = 50
DEFAULT_TOP_K_RERANK = 8
