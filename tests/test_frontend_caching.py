"""How long a browser may keep what the frontend mount serves (Session AS).

The kitchen wall ran a three-week-old build all evening after two deploys:
the page carried a Last-Modified and no Cache-Control, so Chromium guessed it
fresh for two days and never asked for the new one. The page must now be
checked on every open, and only the content-hashed assets kept for good.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.frontend import IMMUTABLE, REVALIDATE, mount_frontend


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text(
        '<!doctype html><script src="/assets/index-abc123.js"></script>', encoding="utf-8"
    )
    (tmp_path / "assets" / "index-abc123.js").write_text("console.log(1)", encoding="utf-8")
    (tmp_path / "favicon.svg").write_text("<svg/>", encoding="utf-8")

    app = FastAPI()

    @app.get("/api/known")
    def known() -> dict[str, bool]:
        return {"ok": True}

    assert mount_frontend(app, tmp_path)
    return TestClient(app)


@pytest.mark.parametrize("path", ["/", "/index.html"])
def test_the_page_is_asked_for_every_time(client: TestClient, path: str) -> None:
    response = client.get(path)
    assert response.status_code == 200
    assert "index-abc123.js" in response.text
    assert response.headers["cache-control"] == REVALIDATE


@pytest.mark.parametrize("path", ["/parent", "/savings/anything"])
def test_an_app_route_falling_back_to_the_page_is_asked_for_too(
    client: TestClient, path: str
) -> None:
    response = client.get(path)
    assert response.status_code == 200
    assert "index-abc123.js" in response.text
    assert response.headers["cache-control"] == REVALIDATE


def test_a_hashed_asset_is_kept(client: TestClient) -> None:
    response = client.get("/assets/index-abc123.js")
    assert response.status_code == 200
    assert response.headers["cache-control"] == IMMUTABLE


def test_an_unhashed_file_is_asked_for(client: TestClient) -> None:
    response = client.get("/favicon.svg")
    assert response.status_code == 200
    assert response.headers["cache-control"] == REVALIDATE


def test_asking_about_an_unchanged_page_costs_a_304(client: TestClient) -> None:
    etag = client.get("/").headers["etag"]
    response = client.get("/", headers={"If-None-Match": etag})
    assert response.status_code == 304
    assert response.headers["cache-control"] == REVALIDATE


def test_the_api_is_untouched(client: TestClient) -> None:
    assert "cache-control" not in client.get("/api/known").headers
    assert client.get("/api/missing").status_code == 404
