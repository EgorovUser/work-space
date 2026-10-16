from __future__ import annotations

from contextvars import ContextVar

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")
user_id_var: ContextVar[str] = ContextVar("user_id", default="-")
module_var: ContextVar[str] = ContextVar("module", default="app")
action_var: ContextVar[str] = ContextVar("action", default="-")
