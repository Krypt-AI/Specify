"""HTTP hardening shared by every response: request ids, security headers, an Origin check
for state-changing requests, and error responses that never reveal internals."""
import logging
import re
import uuid

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from app.core.config import get_settings
from app.core.logging import request_id_var

logger = logging.getLogger(__name__)

REQUEST_ID_HEADER = "X-Request-ID"
_VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9-]{8,64}$")
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
# Interactive API docs load their own scripts and styles; everything else is plain JSON.
_DOCS_PATHS = ("/docs", "/redoc", "/openapi.json")
# Signed by Google rather than sent from a browser; they authenticate themselves.
_WEBHOOK_PREFIX = "/api/webhooks/"


class SecurityMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, allowed_origins: set[str], production: bool) -> None:
        super().__init__(app)
        self.allowed_origins = allowed_origins
        self.production = production

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        incoming = request.headers.get(REQUEST_ID_HEADER, "")
        request_id = incoming if _VALID_REQUEST_ID.match(incoming) else uuid.uuid4().hex
        request.state.request_id = request_id
        token = request_id_var.set(request_id)
        try:
            if self._is_cross_site_write(request):
                response: Response = JSONResponse({"detail": "Cross-site request blocked", "request_id": request_id}, 403)
            else:
                response = await call_next(request)
        finally:
            request_id_var.reset(token)
        self._add_headers(request, response, request_id)
        return response

    def _is_cross_site_write(self, request: Request) -> bool:
        """A browser always sends Origin on cross-site writes; other clients cannot hold the cookie."""
        if request.method in _SAFE_METHODS or request.url.path.startswith(_WEBHOOK_PREFIX):
            return False
        origin = request.headers.get("origin")
        return origin is not None and origin.rstrip("/") not in self.allowed_origins

    def _add_headers(self, request: Request, response: Response, request_id: str) -> None:
        headers = response.headers
        headers[REQUEST_ID_HEADER] = request_id
        headers.setdefault("X-Content-Type-Options", "nosniff")
        headers.setdefault("X-Frame-Options", "DENY")
        headers.setdefault("Referrer-Policy", "no-referrer")
        if not request.url.path.startswith(_DOCS_PATHS):
            headers.setdefault("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
        if request.url.path.startswith("/api/"):
            headers.setdefault("Cache-Control", "no-store")  # personal data never sits in caches
        if self.production:
            headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")


async def _unhandled_error(request: Request, exc: Exception) -> JSONResponse:
    request_id = getattr(request.state, "request_id", "-")
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        {"detail": "Something went wrong. Try again; if it keeps happening, share the request id.", "request_id": request_id},
        status_code=500,
        headers={REQUEST_ID_HEADER: request_id},
    )


def install_http_hardening(app: FastAPI) -> None:
    settings = get_settings()
    origins = {settings.frontend_url.rstrip("/"), settings.backend_url.rstrip("/")}
    app.add_middleware(SecurityMiddleware, allowed_origins=origins, production=settings.is_production)
    app.add_exception_handler(Exception, _unhandled_error)
