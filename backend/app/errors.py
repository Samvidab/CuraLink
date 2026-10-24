"""TRD §6 error model: {"code", "message", "recoverable", "details"}."""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, recoverable: bool = True, details: dict | None = None):
        self.status, self.code, self.message = status, code, message
        self.recoverable, self.details = recoverable, details or {}


def _body(code: str, message: str, recoverable: bool, details: dict | None = None) -> dict:
    return {"code": code, "message": message, "recoverable": recoverable, "details": details or {}}


_DEFAULT_CODES = {400: "BAD_REQUEST", 401: "UNAUTHENTICATED", 403: "FORBIDDEN", 404: "NOT_FOUND", 409: "CONFLICT", 422: "VALIDATION_ERROR"}


def install(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError):
        return JSONResponse(_body(exc.code, exc.message, exc.recoverable, exc.details), status_code=exc.status)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException):
        code = _DEFAULT_CODES.get(exc.status_code, "ERROR")
        return JSONResponse(_body(code, str(exc.detail), exc.status_code < 500), status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError):
        # Strip submitted values from the error so request content (which may be
        # health-related) is never echoed back or logged.
        fields = [{"loc": list(e.get("loc", [])), "msg": e.get("msg")} for e in exc.errors()]
        return JSONResponse(_body("VALIDATION_ERROR", "Request did not match the expected format.", True, {"fields": fields}), status_code=422)
