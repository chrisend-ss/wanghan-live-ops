import threading
from typing import Optional

_active_session_id: Optional[str] = None
_lock = threading.Lock()


def get_active_session_id() -> Optional[str]:
    with _lock:
        return _active_session_id


def set_active_session_id(session_id: Optional[str]) -> None:
    global _active_session_id
    with _lock:
        _active_session_id = session_id
