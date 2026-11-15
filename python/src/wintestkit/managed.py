import math
import struct
from dataclasses import dataclass
from decimal import Decimal as PythonDecimal
from enum import Enum as PythonEnum


@dataclass(frozen=True)
class ManagedArgument:
    type: str
    value: object = None
    kind: str = "value"


def Int32(value: int) -> ManagedArgument:
    if type(value) is not int or not -(2**31) <= value < 2**31:
        raise ValueError("Int32 requires a signed 32-bit integer")
    return ManagedArgument("System.Int32", value)


def Int64(value: int) -> ManagedArgument:
    if type(value) is not int or not -(2**63) <= value < 2**63:
        raise ValueError("Int64 requires a signed 64-bit integer")
    return ManagedArgument("System.Int64", value)


def Single(value: float) -> ManagedArgument:
    if type(value) not in (int, float):
        raise ValueError("Single requires a finite 32-bit float")
    try:
        number = float(value)
        struct.pack("f", number)
    except (OverflowError, struct.error):
        raise ValueError("Single requires a finite 32-bit float") from None
    if not math.isfinite(number) or abs(number) > 3.4028234663852886e38:
        raise ValueError("Single requires a finite 32-bit float")
    return ManagedArgument("System.Single", number)


def Double(value: float) -> ManagedArgument:
    if type(value) not in (int, float):
        raise ValueError("Double requires a finite number")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("Double requires a finite number")
    return ManagedArgument("System.Double", number)


def Decimal(value: object) -> ManagedArgument:
    if not isinstance(value, (PythonDecimal, str)):
        raise ValueError("Decimal requires decimal.Decimal or str")
    number = PythonDecimal(value)
    if not number.is_finite():
        raise ValueError("Decimal requires a finite number")
    return ManagedArgument("System.Decimal", str(number))


def Enum(type_name: object, value: object) -> ManagedArgument:
    if not isinstance(type_name, str) or not type_name or type(value) not in (str, int):
        raise ValueError("Enum requires a type name and a name or integer")
    if type(value) is int and not -(2**63) <= value < 2**63:
        raise ValueError("Enum integer must fit in signed 64 bits")
    return ManagedArgument(type_name, value, "enum")


def Null(type_name: object) -> ManagedArgument:
    if not isinstance(type_name, str) or not type_name:
        raise ValueError("Null requires a CLR type name")
    return ManagedArgument(type_name, True, "null")


def argument(value: object) -> ManagedArgument:
    if isinstance(value, ManagedArgument):
        return value
    if value is None:
        raise ValueError("Use Null(type) for null arguments")
    if isinstance(value, PythonEnum):
        raise ValueError("Use Enum(type, name or integer) for enum arguments")
    if type(value) is str:
        return ManagedArgument("System.String", value)
    if type(value) is bool:
        return ManagedArgument("System.Boolean", value)
    if type(value) is int:
        return Int64(value)
    if type(value) is float:
        return Double(value)
    if isinstance(value, PythonDecimal):
        return Decimal(value)
    raise ValueError("Invalid write argument type")


def encode_argument(value: object) -> dict[str, object]:
    arg = argument(value)
    return {"type": arg.type, arg.kind: arg.value}
