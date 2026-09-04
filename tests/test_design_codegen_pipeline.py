"""Validate source selection and the actual official export boundary."""

import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from lanhu_mcp_server import _generate_design_result


FIXTURE = Path(__file__).parent / "fixtures" / "official_no_permission"
DESIGN = {"id": "sample", "name": "暂无权限"}
PARAMS = {"project_id": "project"}


@pytest.mark.asyncio
async def test_dds_pipeline_preserves_official_export_and_localizes_preview(tmp_path):
    extractor = AsyncMock()
    extractor.get_design_schema_json.return_value = json.loads((FIXTURE / "schema.json").read_text())
    extractor.get_sketch_json.return_value = {}
    result = await _generate_design_result(extractor, DESIGN, PARAMS, tmp_path)
    assert result["success"] and result["source"] == "dds"
    for name in ("index.html", "index.css", "common.css"):
        assert (tmp_path / "sample_dds" / name).read_bytes() == (FIXTURE / name).read_bytes()
    assert len(result["image_url_mapping"]) == 13
    from bs4 import BeautifulSoup
    page = BeautifulSoup(result["html_code"], "html.parser")
    assert len(page.find_all("img")) == 13
    assert all(img["src"] in result["image_url_mapping"] for img in page.find_all("img"))
    assert "./assets/" not in page.get_text()


@pytest.mark.asyncio
async def test_figma_fallback_uses_same_renderer(tmp_path, monkeypatch):
    from lanhu_codegen import figma_schema
    schema = json.loads((FIXTURE / "schema.json").read_text())
    seen = []
    def adapt(raw, *, asset_loader):
        assert callable(asset_loader)
        seen.append(raw)
        return schema
    monkeypatch.setattr(figma_schema, "figma_to_dds_schema", adapt)
    extractor = AsyncMock()
    extractor.get_design_schema_json.side_effect = RuntimeError("DDS unavailable")
    extractor.get_sketch_json.return_value = {"meta": {"host": {"name": "figma"}}}
    result = await _generate_design_result(extractor, DESIGN, PARAMS, tmp_path)
    assert result["success"] and result["source"] == "figma"
    assert len(seen) == 1
    assert result["dds_error"] == "DDS unavailable"
    assert (tmp_path / "sample_figma" / "index.html").read_bytes() == (FIXTURE / "index.html").read_bytes()


@pytest.mark.asyncio
async def test_unsupported_figma_is_reported_without_background_fallback(tmp_path, monkeypatch):
    from lanhu_codegen import figma_schema
    def reject(_, **kwargs):
        raise ValueError("layer Vector123: missing vector geometry and export asset")
    monkeypatch.setattr(figma_schema, "figma_to_dds_schema", reject)
    extractor = AsyncMock()
    extractor.get_design_schema_json.side_effect = RuntimeError("DDS unavailable")
    extractor.get_sketch_json.return_value = {}
    result = await _generate_design_result(extractor, DESIGN, PARAMS, tmp_path)
    assert not result["success"]
    assert "DDS unavailable" in result["error"] and "Vector123" in result["error"]
    assert "html_code" not in result and "sketch_html" not in result
    assert not list(tmp_path.iterdir())


def test_merge_asset_downloads_are_cached_and_do_not_forward_account_headers(monkeypatch):
    import httpx
    import lanhu_mcp_server as server
    from lanhu_codegen import figma_schema

    requests = []
    client = httpx.Client

    def respond(request):
        requests.append(request)
        return httpx.Response(200, content=b"source PNG bytes")

    def isolated_client(**kwargs):
        assert "headers" not in kwargs and "cookies" not in kwargs and "auth" not in kwargs
        return client(transport=httpx.MockTransport(respond), **kwargs)

    def convert(raw, *, asset_loader):
        assert raw == {"sample": True}
        assert asset_loader("https://assets.example.com/image.png") == b"source PNG bytes"
        assert asset_loader("https://assets.example.com/image.png") == b"source PNG bytes"
        return {"converted": True}

    monkeypatch.setattr(server.httpx, "Client", isolated_client)
    monkeypatch.setattr(figma_schema, "figma_to_dds_schema", convert)
    assert server._convert_figma_with_assets({"sample": True}) == {"converted": True}
    assert len(requests) == 1
    assert "authorization" not in requests[0].headers and "cookie" not in requests[0].headers


def test_schema_warnings_include_descendant_resource_and_border_differences():
    from lanhu_mcp_server import _schema_conversion_warnings
    border = {"layerId": "header", "reason": "DDS expands per-edge stroke"}
    image = {"layerIds": ["a", "b"], "reason": "image merge skipped"}
    schema = {"children": [{"conversionWarnings": [border], "children": [
        {"layoutWarnings": [image], "children": []}]}]}
    assert _schema_conversion_warnings(schema) == [border, image]
