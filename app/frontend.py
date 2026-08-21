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
from starlette.exceptions import HTTPException as StarletteHTTPException


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

    async def get_response(self, path: str, scope):
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code == 404 and not self._is_reserved(scope):
                return await super().get_response("index.html", scope)
            raise


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
