"""Safe structured request logging without request or response payloads."""

import logging
import sys
from time import perf_counter

from fastapi import Request

LOGGER_NAME = "english_for_developers.request"
HANDLER_NAME = "eds-request-log"
_LOG_FORMAT = "%(asctime)s %(message)s"

_logger = logging.getLogger(LOGGER_NAME)


def configure_request_logging() -> None:
    """Attach one stdout handler to the request logger, unless it already exists."""
    _logger.setLevel(logging.INFO)
    if any(handler.name == HANDLER_NAME for handler in _logger.handlers):
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(_LOG_FORMAT))
    handler.name = HANDLER_NAME
    _logger.addHandler(handler)


def _route_template(request: Request, status_code: int) -> str:
    """Return the matched route template, never the raw request path."""
    if status_code == 405:
        return "unmatched"
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    return path if isinstance(path, str) else "unmatched"


def log_request(request: Request, *, status_code: int, started_at: float) -> None:
    """Emit the single safe access-log record for a finished request."""
    duration_ms = int((perf_counter() - started_at) * 1000)
    _logger.info(
        "request request_id=%s method=%s route=%s status=%d duration_ms=%d error_code=%s",
        getattr(request.state, "request_id", "-"),
        request.method,
        _route_template(request, status_code),
        status_code,
        duration_ms,
        getattr(request.state, "error_code", None) or "-",
    )
