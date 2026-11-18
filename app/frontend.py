"""Serving the built React bundle from FastAPI.

The container is same-origin: one process answers both the SPA and the API,
so there is no CORS and no hostname baked into the bundle. Only the container
does this — in development the bundle does not exist and Vite serves it
itself, proxying /health and /api to this API instead.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.responses import Response
from starlette.exceptions import HTTPException as StarletteHTTPException


# The page itself, and every route that falls back to it, is checked with the
# server on every open. Without a Cache-Control header the browser guesses how
# long a page stays fresh — 10% of its age since Last-Modified — and a bundle
# built three weeks before was trusted for two days: the kitchen wall ran the
# 28 October build all evening after two deploys on 18 Nov 2026, never asking
# for the new page (Session AS). "no-cache" still caches; it only means ask
# first, and the ETag makes an unchanged page a 304.
REVALIDATE = "no-cache"

# Vite names every built asset after a hash of its content, so a name never
# changes meaning: a new build is a new name, reached through the page above.
IMMUTABLE = "public, max-age=31536000, immutable"


def cache_control(url_path: str) -> str:
    """The Cache-Control for one served path: assets for ever, all else asked."""
    return IMMUTABLE if url_path.strip("/").startswith("assets/") else REVALIDATE


class SPAStaticFiles(StaticFiles):
    """StaticFiles that falls back to index.html.

    A single-page app owns its own routing, so a page like the week view is a
    real screen to the browser but not a file on disk. Without this, a hard
    reload would 404 — the app would only work by entering through "/".

    Safe *because* the API is namespaced under /api and /health sits outside
    it: this mount is added last, so every real route matches first and only
    an unmatched path reaches here. An unmatched path under the reserved
    prefix still 404s rather than getting index.html — turning that into 200
    would hand an integration client HTML to parse as JSON.
    """

    def __init__(self, *args, reserved_prefixes: tuple[str, ...] = ("api",), **kwargs):
        super().__init__(*args, **kwargs)
        self.reserved_prefixes = tuple(p.strip("/") for p in reserved_prefixes)

    def _is_reserved(self, scope) -> bool:
        # The scope path, not the `path` argument: that one has been through
        # os.path.normpath, so on Windows it arrives with backslashes and a
        # check for "api/" silently never matches. The scope path is
        # URL-shaped on every platform.
        url_path = scope.get("path", "").strip("/")
        return any(
            url_path == prefix or url_path.startswith(f"{prefix}/")
            for prefix in self.reserved_prefixes
        )

    async def get_response(self, path: str, scope) -> Response:
        try:
            response = await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code == 404 and not self._is_reserved(scope):
                response = await super().get_response("index.html", scope)
                # The fallback is the page, whatever path asked for it.
                response.headers["Cache-Control"] = REVALIDATE
                return response
            raise
        response.headers["Cache-Control"] = cache_control(scope.get("path", ""))
        return response


def mount_frontend(app: FastAPI, directory: Path) -> bool:
    """Serve `directory` at /. Returns whether it was mounted.

    Call AFTER every API router and mount: Starlette matches routes in the
    order they were added, and this one matches everything.
    """
    index = directory / "index.html"
    if not index.is_file():
        # No bundle: an API-only process, which is how the dev server and the
        # test suite run. Not an error.
        return False

    app.mount(
        "/",
        SPAStaticFiles(directory=directory, html=True, reserved_prefixes=("api",)),
        name="frontend",
    )
    return True
