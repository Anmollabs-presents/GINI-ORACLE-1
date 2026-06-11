# ============================================================
# GINI-ORACLE-1 — Confirmation Manager
# actions/confirmation_manager.py
# ============================================================
"""
Manages pending confirmations for dangerous system actions.

Flow:
  User: "shutdown"
  Gini: "Are you sure you want to shut down? Say 'yes' to confirm."
  User: "yes"
  Gini: [executes shutdown]

Features:
  - Per-user pending confirmation state
  - Configurable expiry timeout (default 30s)
  - Whitelist of commands requiring confirmation
  - Thread-safe
"""

import time
import threading
from dataclasses import dataclass, field
from typing import Optional, Dict, Callable
from utils.logger import get_logger

log = get_logger(__name__)

# Commands that MUST be confirmed before execution
DANGEROUS_COMMANDS = {
    "shutdown", "restart", "reboot", "kill", "force_shutdown",
}

# Confirmation expiry in seconds
CONFIRM_EXPIRY = 30.0

# Words accepted as confirmation
CONFIRM_WORDS = {"yes", "yeah", "yep", "confirm", "do it", "go ahead", "sure", "ok", "okay"}
CANCEL_WORDS  = {"no", "nope", "cancel", "stop", "abort", "never mind", "nevermind"}


@dataclass
class PendingConfirmation:
    """A confirmation request waiting for user response."""
    user_id: str
    action: str                         # e.g. "shutdown"
    payload: dict                       # Args to pass to executor on confirm
    prompt: str                         # Message shown to user
    callback: Callable                  # Async fn to call on confirm
    created_at: float = field(default_factory=time.time)

    @property
    def is_expired(self) -> bool:
        return time.time() - self.created_at > CONFIRM_EXPIRY

    @property
    def time_remaining(self) -> float:
        return max(0.0, CONFIRM_EXPIRY - (time.time() - self.created_at))


class ConfirmationManager:
    """
    Thread-safe store for pending dangerous action confirmations.
    One pending confirmation per user at a time.
    """

    def __init__(self):
        self._pending: Dict[str, PendingConfirmation] = {}
        self._lock = threading.Lock()
        log.debug("ConfirmationManager initialized")

    def requires_confirmation(self, action: str) -> bool:
        """Check if an action requires user confirmation."""
        return action.lower() in DANGEROUS_COMMANDS

    def request(
        self,
        user_id: str,
        action: str,
        payload: dict,
        prompt: str,
        callback: Callable,
    ) -> str:
        """
        Register a pending confirmation.
        Returns the prompt to show the user.
        Overwrites any existing pending confirmation for this user.
        """
        with self._lock:
            self._pending[user_id] = PendingConfirmation(
                user_id=user_id,
                action=action,
                payload=payload,
                prompt=prompt,
                callback=callback,
            )
        log.info(f"Confirmation requested: [{user_id}] → {action}")
        return prompt

    def is_confirmation(self, text: str) -> bool:
        """Check if user's response is a confirmation word."""
        return text.lower().strip().rstrip("!.") in CONFIRM_WORDS

    def is_cancellation(self, text: str) -> bool:
        """Check if user's response is a cancellation word."""
        return text.lower().strip().rstrip("!.") in CANCEL_WORDS

    def has_pending(self, user_id: str) -> bool:
        """Check if user has a non-expired pending confirmation."""
        with self._lock:
            pending = self._pending.get(user_id)
            if pending and pending.is_expired:
                del self._pending[user_id]
                return False
            return pending is not None

    def get_pending(self, user_id: str) -> Optional[PendingConfirmation]:
        """Get pending confirmation for a user. Returns None if expired."""
        with self._lock:
            pending = self._pending.get(user_id)
            if pending and pending.is_expired:
                del self._pending[user_id]
                log.debug(f"Confirmation expired for [{user_id}]")
                return None
            return pending

    async def confirm(self, user_id: str) -> Optional[dict]:
        """
        Execute the pending action for a user.
        Returns handler result dict, or None if no pending confirmation.
        """
        pending = self.get_pending(user_id)
        if not pending:
            return None

        with self._lock:
            self._pending.pop(user_id, None)

        log.info(f"Confirmation accepted: [{user_id}] → {pending.action}")
        try:
            return await pending.callback(**pending.payload)
        except Exception as e:
            log.error(f"Confirmed action error: {e}")
            return {
                "status": "error",
                "intent": "system_control",
                "response": f"Failed to execute {pending.action}: {str(e)}",
            }

    def cancel(self, user_id: str) -> bool:
        """Cancel a pending confirmation. Returns True if one existed."""
        with self._lock:
            if user_id in self._pending:
                action = self._pending[user_id].action
                del self._pending[user_id]
                log.info(f"Confirmation cancelled: [{user_id}] → {action}")
                return True
        return False

    def clear_expired(self) -> int:
        """Remove all expired confirmations. Returns count removed."""
        with self._lock:
            expired = [
                uid for uid, p in self._pending.items() if p.is_expired
            ]
            for uid in expired:
                del self._pending[uid]
        return len(expired)

    @property
    def pending_count(self) -> int:
        return len(self._pending)


# Singleton
_manager: Optional[ConfirmationManager] = None

def get_confirmation_manager() -> ConfirmationManager:
    global _manager
    if _manager is None:
        _manager = ConfirmationManager()
    return _manager


__all__ = [
    "ConfirmationManager", "PendingConfirmation",
    "get_confirmation_manager",
    "DANGEROUS_COMMANDS", "CONFIRM_WORDS", "CANCEL_WORDS",
]
