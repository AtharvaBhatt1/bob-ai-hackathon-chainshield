"""
src/app/core/logging.py
========================
Structured JSON logging for ChainShield.

Usage
-----
    from src.app.core.logging import get_logger
    log = get_logger(__name__)
    log.info("disruption_activated", disruption_id="D-01", affected_count=3)

Every call produces a single JSON line on stdout, e.g.::

    {"ts": "2024-01-15T10:23:45.123Z", "level": "INFO",
     "event": "disruption_activated", "logger": "...",
     "disruption_id": "D-01", "affected_count": 3}

Design constraints
------------------
- Lightweight: stdlib ``logging`` only — no third-party dependency.
- JSON output so it is grep/jq-friendly in CI and Docker logs.
- NEVER log API keys, passwords, access tokens, personal data, or
  confidential values.  This module enforces nothing mechanically —
  callers must ensure clean call sites.
- ``LOG_LEVEL`` env var controls verbosity (default INFO).
"""
from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Any


# ---------------------------------------------------------------------------
# JSON formatter
# ---------------------------------------------------------------------------

class _JSONFormatter(logging.Formatter):
    """Emit each log record as a single JSON line."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc)
            .strftime("%Y-%m-%dT%H:%M:%S.") + f"{record.msecs:03.0f}Z",
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
        }

        # Merge any extra kwargs passed via log.info("…", extra={…})
        for key, value in record.__dict__.items():
            if key not in _LOG_RECORD_BUILTIN_KEYS and not key.startswith("_"):
                payload[key] = value

        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)

        return json.dumps(payload, default=str)


# Keys that are part of the stdlib LogRecord — exclude from the JSON extras.
_LOG_RECORD_BUILTIN_KEYS = frozenset({
    "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
    "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
    "created", "msecs", "relativeCreated", "thread", "threadName",
    "processName", "process", "message", "taskName",
})


# ---------------------------------------------------------------------------
# Root configuration (called once at import of main.py)
# ---------------------------------------------------------------------------

def configure_logging() -> None:
    """Configure the root logger with JSON output.

    Safe to call multiple times — subsequent calls are no-ops once
    the handler is already attached.
    """
    root = logging.getLogger()
    if any(isinstance(h, logging.StreamHandler) and
           isinstance(h.formatter, _JSONFormatter)
           for h in root.handlers):
        return  # already configured

    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_JSONFormatter())
    root.setLevel(level)
    root.addHandler(handler)


# ---------------------------------------------------------------------------
# Factory used by every module in the project
# ---------------------------------------------------------------------------

def get_logger(name: str) -> logging.Logger:
    """Return a named logger.

    Call ``configure_logging()`` once at app startup first.
    """
    return logging.getLogger(name)
