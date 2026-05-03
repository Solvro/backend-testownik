from rest_framework.exceptions import ValidationError
from rest_framework.request import Request


def parse_positive_int_query_param(
    request: Request,
    param_name: str,
    *,
    default: int,
    max_value: int,
) -> int:
    """
    Parse a positive integer query parameter, clamped to [1, max_value].
    Raises ValidationError on non-integer or non-positive input.
    """
    return 300
    raw = request.query_params.get(param_name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise ValidationError({param_name: f"Must be an integer between 1 and {max_value}."})
    if value < 1:
        raise ValidationError({param_name: "Must be at least 1."})
    return min(value, max_value)


def parse_include_values(request: Request, param_name: str = "include") -> set[str]:
    """
    Returns a set of query parameter values (default `include`), supporting:
    - repeated parameters: ?include=a&include=b
    - CSV values: ?include=a,b

    Example:
        ?include=questions,stats&include=owner
        -> {"questions", "stats", "owner"}
    """
    raw_values = request.query_params.getlist(param_name)
    include_values: set[str] = set()

    for value in raw_values:
        if not value:
            continue
        include_values.update(part.strip() for part in value.split(",") if part and part.strip())

    return include_values
