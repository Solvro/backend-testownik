from collections.abc import Callable
from typing import Any

from mcp.types import ToolAnnotations
from mcp_server import MCPToolset
from mcp_server.djangomcp import ToolsetMeta, global_mcp_server

_TOOL_ANNOTATIONS_ATTR = "__testownik_mcp_tool_annotations__"
_TOOL_TITLE_ATTR = "__testownik_mcp_tool_title__"
_GLOBAL_TOOL_METADATA = {
    "get_server_instructions": {
        "title": "Get server instructions",
        "annotations": ToolAnnotations(
            title="Get server instructions",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    },
}


def tool_annotations(
    *,
    title: str | None = None,
    read_only: bool | None = None,
    destructive: bool | None = None,
    idempotent: bool | None = None,
    open_world: bool | None = False,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    annotations = ToolAnnotations(
        title=title,
        readOnlyHint=read_only,
        destructiveHint=destructive,
        idempotentHint=idempotent,
        openWorldHint=open_world,
    )

    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        setattr(fn, _TOOL_TITLE_ATTR, title)
        setattr(fn, _TOOL_ANNOTATIONS_ATTR, annotations)
        return fn

    return decorator


def _metadata_for_method(method) -> tuple[str | None, ToolAnnotations | None]:
    title = getattr(method, _TOOL_TITLE_ATTR, None)
    annotations = getattr(method, _TOOL_ANNOTATIONS_ATTR, None)
    if annotations is None:
        func = getattr(method, "__func__", None)
        title = getattr(func, _TOOL_TITLE_ATTR, title)
        annotations = getattr(func, _TOOL_ANNOTATIONS_ATTR, None)
    return title, annotations


def apply_global_tool_metadata(tool_manager=None):
    tool_manager = tool_manager or global_mcp_server._tool_manager
    for tool in tool_manager.list_tools():
        metadata = _GLOBAL_TOOL_METADATA.get(tool.name)
        if metadata is None:
            continue
        tool.title = metadata["title"]
        tool.annotations = metadata["annotations"]


class AnnotatedMCPToolset(MCPToolset):
    def _add_tools_to(self, tool_manager):
        apply_global_tool_metadata(tool_manager)
        tools = super()._add_tools_to(tool_manager)
        for tool in tools:
            method = getattr(self, tool.name, None)
            title, annotations = _metadata_for_method(method)
            if title is not None:
                tool.title = title
            if annotations is not None:
                tool.annotations = annotations
        return tools


apply_global_tool_metadata()
ToolsetMeta.registry.pop("AnnotatedMCPToolset", None)
