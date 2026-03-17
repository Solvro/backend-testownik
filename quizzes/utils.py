from rest_framework.request import Request


def parse_include_values(request: Request, param_name: str = "include") -> set[str]:
    """
    Zwraca zbiór wartości parametru query (domyślnie `include`), wspierając:
    - powtarzane parametry: ?include=a&include=b
    - wartości CSV: ?include=a,b

    Przykład:
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
