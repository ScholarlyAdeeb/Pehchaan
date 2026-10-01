"""
Checkpoint Access Control.

Enforces that engine instances only serve scans for their assigned checkpoints.
This prevents a compromised engine instance from being used to scan documents
at unauthorized border posts.
"""
from __future__ import annotations

from app.config import get_settings


class CheckpointAccessError(Exception):
    """Raised when a request violates checkpoint access policy."""
    pass


def require_checkpoint_access(checkpoint_id: str) -> None:
    """
    Verify that the current engine instance is authorized to serve the given checkpoint.

    Raises:
        CheckpointAccessError: If the checkpoint is not in the allowed list.
    """
    settings = get_settings()
    allowed = settings.ENGINE_CHECKPOINT_IDS

    if not allowed:
        # No restriction configured — allow all checkpoints
        return

    if checkpoint_id not in allowed:
        raise CheckpointAccessError(
            f"Checkpoint '{checkpoint_id}' not authorized for this engine instance. "
            f"Allowed: {', '.join(allowed)}"
        )


def get_allowed_checkpoints() -> list[str]:
    """Get the list of checkpoint IDs this engine instance is authorized to serve."""
    settings = get_settings()
    return settings.ENGINE_CHECKPOINT_IDS.copy()


def is_checkpoint_allowed(checkpoint_id: str) -> bool:
    """Check if a checkpoint ID is allowed without raising."""
    settings = get_settings()
    allowed = settings.ENGINE_CHECKPOINT_IDS
    if not allowed:
        return True
    return checkpoint_id in allowed