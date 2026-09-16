from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass


@dataclass
class CallMeter:
    max_output_tokens: int
    input_tokens: int | None = None
    output_tokens: int | None = None


current_meter: ContextVar[CallMeter | None] = ContextVar("buno_call_meter", default=None)


@contextmanager
def metered_call(max_output_tokens):
    meter = CallMeter(max_output_tokens)
    token = current_meter.set(meter)
    try:
        yield meter
    finally:
        current_meter.reset(token)
