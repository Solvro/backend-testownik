def deprecate_non_api_paths(result, generator, request, public):
    """
    Post-processing hook to mark all URLs that do not start with /api/ as deprecated
    and group them under a 'Legacy' tag.
    """
    paths = result.get("paths", {})

    for path, methods in paths.items():
        if not path.startswith("/api/"):
            for method, operation in methods.items():
                operation["deprecated"] = True

                tags = operation.get("tags", [])
                if "Legacy" not in tags:
                    tags.append("Legacy")
                    operation["tags"] = tags

    return result
