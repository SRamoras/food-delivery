"""Domain exceptions and the handler that turns them into HTTP responses."""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class DomainError(Exception):
    status_code = 400

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class NotFound(DomainError):
    status_code = 404


class Conflict(DomainError):
    """Refused by a business rule: stock, already taken, capacity, invalid transition..."""

    status_code = 409


# No global IntegrityError handler on purpose. In real mode, a service catches
# IntegrityError only where a constraint backs a rule (e.g. UNIQUE order_id on
# deliveries) and raises Conflict. Anything else stays a 500: in naive mode that is
# how the concurrency test shows the race, and an unexpected violation (a bug) must
# not look like a normal 409.


def _domain_error(_: Request, exc: DomainError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(DomainError, _domain_error)
