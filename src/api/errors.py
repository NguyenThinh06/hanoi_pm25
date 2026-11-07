"""Consistent, non-sensitive JSON errors for all API endpoints."""

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

logger = logging.getLogger(__name__)
DATABASE_MESSAGE = "Cơ sở dữ liệu tạm thời chưa sẵn sàng."
INTERNAL_MESSAGE = "Không thể xử lý yêu cầu vào lúc này."


class APIError(Exception):
    def __init__(self, status: int, code: str, message: str):
        self.status = status
        self.code = code
        self.message = message
        super().__init__(message)


def error_response(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message}})


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(APIError)
    async def api_error(_: Request, exc: APIError) -> JSONResponse:
        return error_response(exc.status, exc.code, exc.message)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(_: Request, exc: RequestValidationError) -> JSONResponse:
        fields = sorted({str(error["loc"][-1]) for error in exc.errors()})
        return error_response(422, "INVALID_REQUEST", "Tham số không hợp lệ: " + ", ".join(fields) + ".")

    @app.exception_handler(HTTPException)
    async def http_error(_: Request, exc: HTTPException) -> JSONResponse:
        code = "NOT_FOUND" if exc.status_code == 404 else "INVALID_REQUEST"
        message = "Không tìm thấy đường dẫn." if exc.status_code == 404 else "Yêu cầu không được hỗ trợ."
        response = error_response(exc.status_code, code, message)
        response.headers.update(exc.headers or {})
        return response

    @app.exception_handler(Exception)
    async def unexpected_error(_: Request, exc: Exception) -> JSONResponse:
        # Do not include DSNs, SQL, input values or exception messages in logs/responses.
        logger.error("Unexpected API failure (%s)", type(exc).__name__)
        return error_response(500, "INTERNAL_ERROR", INTERNAL_MESSAGE)
