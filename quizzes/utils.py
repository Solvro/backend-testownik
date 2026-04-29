from rest_framework.request import Request


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
