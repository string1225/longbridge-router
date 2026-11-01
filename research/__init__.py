"""Read-only research tools; no broker trading operations."""

import hashlib
import json


def fingerprint(value):
    """Stable digest for provenance and revision checks, independent of retrieval time."""
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()
