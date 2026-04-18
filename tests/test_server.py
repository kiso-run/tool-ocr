"""Tests for the MCP tool surface exposed by kiso_ocr_mcp.server."""
from __future__ import annotations

import json
from unittest.mock import patch


def _decode(result) -> dict:
    blocks = result if isinstance(result, list) else list(result)
    return json.loads(blocks[0].text)


def test_mcp_instance_named():
    from kiso_ocr_mcp import server
    assert server.mcp.name == "kiso-ocr"


async def test_all_tools_registered():
    from kiso_ocr_mcp import server
    tools = await server.mcp.list_tools()
    names = {t.name for t in tools}
    assert {"ocr_image", "describe_image", "image_info", "doctor"} <= names


async def test_ocr_image_delegates():
    from kiso_ocr_mcp import server
    stub = {
        "success": True, "text": "hi", "has_text": True, "format": "png",
        "width": 64, "height": 48, "truncated": False, "stderr": "",
    }
    with patch(
        "kiso_ocr_mcp.server.ocr_runner.ocr_image", return_value=stub,
    ) as run:
        result = await server.mcp.call_tool(
            "ocr_image", {"file_path": "/tmp/x.png"},
        )
    run.assert_called_once_with(file_path="/tmp/x.png")
    assert _decode(result) == stub


async def test_describe_image_delegates():
    from kiso_ocr_mcp import server
    stub = {
        "success": True, "description": "cat", "format": "png",
        "width": 64, "height": 48, "truncated": False, "stderr": "",
    }
    with patch(
        "kiso_ocr_mcp.server.ocr_runner.describe_image", return_value=stub,
    ) as run:
        result = await server.mcp.call_tool(
            "describe_image", {"file_path": "/tmp/x.png"},
        )
    run.assert_called_once_with(file_path="/tmp/x.png")
    assert _decode(result) == stub


async def test_image_info_delegates():
    from kiso_ocr_mcp import server
    stub = {
        "success": True, "file_name": "x.png", "size_bytes": 100,
        "format": "png", "width": 64, "height": 48, "stderr": "",
    }
    with patch(
        "kiso_ocr_mcp.server.ocr_runner.image_info", return_value=stub,
    ) as run:
        result = await server.mcp.call_tool(
            "image_info", {"file_path": "/tmp/x.png"},
        )
    run.assert_called_once_with(file_path="/tmp/x.png")
    assert _decode(result) == stub


async def test_doctor_delegates():
    from kiso_ocr_mcp import server
    stub = {"healthy": True, "issues": []}
    with patch(
        "kiso_ocr_mcp.server.ocr_runner.check_health", return_value=stub,
    ) as run:
        result = await server.mcp.call_tool("doctor", {})
    run.assert_called_once_with()
    assert _decode(result) == stub


def test_main_calls_run():
    from kiso_ocr_mcp import server
    with patch.object(server.mcp, "run") as run:
        server.main()
    run.assert_called_once()
