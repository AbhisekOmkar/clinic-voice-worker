import logging
import sys
from contextvars import ContextVar

from loguru import logger

from app.config.settings import settings

call_id_var: ContextVar[str | None] = ContextVar("call_id", default=None)
phone_var: ContextVar[str | None] = ContextVar("phone", default=None)


def _context_patcher(record):
    record["extra"].setdefault("call_id", call_id_var.get())


class InterceptHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno
        logger.opt(depth=6, exception=record.exc_info).log(level, record.getMessage())


def configure_logging() -> None:
    logger.remove()
    logger.configure(patcher=_context_patcher)
    logger.add(
        sys.stdout,
        level=settings.log_level.upper(),
        format=(
            "<green>{time:HH:mm:ss.SSS}</green> | <level>{level: <7}</level> | "
            "<magenta>{extra[call_id]}</magenta> | "
            "<cyan>{name}</cyan>:<cyan>{line}</cyan> | <level>{message}</level>"
        ),
    )
    logging.basicConfig(handlers=[InterceptHandler()], level=logging.INFO, force=True)
    for noisy in ("httpx", "httpcore", "urllib3", "websockets", "openai", "numba"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def bind_call(call_id: str | None, phone: str | None = None) -> None:
    call_id_var.set(call_id)
    phone_var.set(phone)
