"""Small, runtime-independent validation helpers. All USD amounts use microdollars."""
import hashlib
import json
import re
import time
from decimal import Decimal, InvalidOperation, ROUND_CEILING


class Blocked(Exception):
    """A stable, non-secret error code safe to show in the dashboard."""


def now():
    return int(time.time())


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def integer(value, minimum=0, maximum=10**12):
    if type(value) is not int or not minimum <= value <= maximum:
        raise Blocked("invalid_integer")
    return value


def decimal(value):
    if isinstance(value, bool):
        raise Blocked("invalid_number")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise Blocked("invalid_number") from None
    if not result.is_finite() or abs(result) > Decimal("1e30"):
        raise Blocked("invalid_number")
    return result


def usd(value):
    return int((decimal(value) * 1_000_000).to_integral_value(rounding=ROUND_CEILING))


def address(value):
    if not isinstance(value, str) or not re.fullmatch(r"0x[0-9a-fA-F]{40}", value):
        raise Blocked("invalid_address")
    if int(value, 16) == 0:
        raise Blocked("zero_address")
    return value.lower()


def json_object(text, limit=65536):
    if len(text.encode()) > limit:
        raise Blocked("body_too_large")
    def pairs(items):
        d = {}
        for k, v in items:
            if k in d:
                raise Blocked("duplicate_json_key")
            d[k] = v
        return d
    try:
        value = json.loads(text, object_pairs_hook=pairs, parse_constant=lambda _: (_ for _ in ()).throw(Blocked("invalid_json")))
    except (ValueError, TypeError):
        raise Blocked("invalid_json") from None
    if not isinstance(value, dict):
        raise Blocked("expected_object")
    return value
