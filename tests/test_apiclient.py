"""Tests for crashbytes-apiclient."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import httpx

from crashbytes_apiclient import (
    ApiClient,
    BearerAuth,
    CursorPaginator,
    PageNumberPaginator,
    RateLimitMiddleware,
    RefreshableAuth,
    RetryMiddleware,
)

# ── Auth Tests ──────────────────────────────────────────────────────


class TestBearerAuth:
    def test_adds_header(self) -> None:
        auth = BearerAuth("mytoken")
        request = httpx.Request("GET", "https://example.com")
        flow = auth.auth_flow(request)
        modified = next(flow)
        assert modified.headers["Authorization"] == "Bearer mytoken"


class TestRefreshableAuth:
    def test_no_refresh_on_success(self) -> None:
        auth = RefreshableAuth("token1", lambda: "token2")
        request = httpx.Request("GET", "https://example.com")
        flow = auth.auth_flow(request)
        modified = next(flow)
        assert modified.headers["Authorization"] == "Bearer token1"

    def test_refresh_on_401(self) -> None:
        refresh_fn = MagicMock(return_value="token2")
        auth = RefreshableAuth("token1", refresh_fn)
        request = httpx.Request("GET", "https://example.com")
        flow = auth.auth_flow(request)
        modified = next(flow)
        assert modified.headers["Authorization"] == "Bearer token1"

        # Simulate 401 response
        response = httpx.Response(401, request=request)
        modified = flow.send(response)
        assert modified.headers["Authorization"] == "Bearer token2"
        refresh_fn.assert_called_once()


# ── Middleware Tests ────────────────────────────────────────────────


class TestRetryMiddleware:
    def test_should_retry_on_503(self) -> None:
        mw = RetryMiddleware()
        response = httpx.Response(503)
        assert mw.should_retry(response) is True

    def test_should_not_retry_on_200(self) -> None:
        mw = RetryMiddleware()
        response = httpx.Response(200)
        assert mw.should_retry(response) is False

    def test_process_request_passthrough(self) -> None:
        mw = RetryMiddleware()
        request = httpx.Request("GET", "https://example.com")
        assert mw.process_request(request) is request

    def test_process_response_passthrough(self) -> None:
        mw = RetryMiddleware()
        response = httpx.Response(200)
        assert mw.process_response(response) is response


class TestRateLimitMiddleware:
    def test_process_request(self) -> None:
        mw = RateLimitMiddleware(min_interval=0.0)
        request = httpx.Request("GET", "https://example.com")
        result = mw.process_request(request)
        assert result is request

    def test_process_response_passthrough(self) -> None:
        mw = RateLimitMiddleware()
        response = httpx.Response(200)
        assert mw.process_response(response) is response


# ── Paginator Tests ─────────────────────────────────────────────────


class TestCursorPaginator:
    def test_get_results(self) -> None:
        pag = CursorPaginator()
        data: dict[str, Any] = {"results": [1, 2, 3], "next_cursor": "abc"}
        assert pag.get_results(data) == [1, 2, 3]

    def test_get_next_params(self) -> None:
        pag = CursorPaginator()
        data: dict[str, Any] = {"results": [], "next_cursor": "abc"}
        assert pag.get_next_params(data) == {"cursor": "abc"}

    def test_get_next_params_none(self) -> None:
        pag = CursorPaginator()
        data: dict[str, Any] = {"results": [], "next_cursor": None}
        assert pag.get_next_params(data) is None

    def test_get_next_params_missing(self) -> None:
        pag = CursorPaginator()
        data: dict[str, Any] = {"results": []}
        assert pag.get_next_params(data) is None

    def test_custom_keys(self) -> None:
        pag = CursorPaginator(
            cursor_param="after", cursor_path="paging.next", results_path="data"
        )
        data: dict[str, Any] = {"data": [1], "paging.next": "xyz"}
        assert pag.get_results(data) == [1]
        assert pag.get_next_params(data) == {"after": "xyz"}


class TestPageNumberPaginator:
    def test_get_results(self) -> None:
        pag = PageNumberPaginator()
        data: dict[str, Any] = {"results": [1, 2], "total_pages": 3}
        assert pag.get_results(data) == [1, 2]

    def test_get_next_params(self) -> None:
        pag = PageNumberPaginator()
        data: dict[str, Any] = {"results": [], "total_pages": 3}
        params = pag.get_next_params(data)
        assert params == {"page": "2"}

    def test_get_next_params_last_page(self) -> None:
        pag = PageNumberPaginator()
        pag._current_page = 3
        data: dict[str, Any] = {"results": [], "total_pages": 3}
        assert pag.get_next_params(data) is None


# ── ApiClient Tests ─────────────────────────────────────────────────


class TestApiClient:
    def test_context_manager(self) -> None:
        transport = httpx.MockTransport(
            lambda req: httpx.Response(200, json={"ok": True})
        )
        with ApiClient("https://api.example.com") as client:
            client._client = httpx.Client(
                base_url="https://api.example.com", transport=transport
            )
            resp = client.get("/test")
            assert resp.status_code == 200
            assert resp.json() == {"ok": True}

    def test_post(self) -> None:
        transport = httpx.MockTransport(
            lambda req: httpx.Response(201, json={"id": 1})
        )
        with ApiClient("https://api.example.com") as client:
            client._client = httpx.Client(
                base_url="https://api.example.com", transport=transport
            )
            resp = client.post("/items", json={"name": "test"})
            assert resp.status_code == 201

    def test_put(self) -> None:
        transport = httpx.MockTransport(
            lambda req: httpx.Response(200, json={"updated": True})
        )
        with ApiClient("https://api.example.com") as client:
            client._client = httpx.Client(
                base_url="https://api.example.com", transport=transport
            )
            resp = client.put("/items/1", json={"name": "updated"})
            assert resp.status_code == 200

    def test_patch(self) -> None:
        transport = httpx.MockTransport(
            lambda req: httpx.Response(200)
        )
        with ApiClient("https://api.example.com") as client:
            client._client = httpx.Client(
                base_url="https://api.example.com", transport=transport
            )
            resp = client.patch("/items/1", json={"name": "patched"})
            assert resp.status_code == 200

    def test_delete(self) -> None:
        transport = httpx.MockTransport(
            lambda req: httpx.Response(204)
        )
        with ApiClient("https://api.example.com") as client:
            client._client = httpx.Client(
                base_url="https://api.example.com", transport=transport
            )
            resp = client.delete("/items/1")
            assert resp.status_code == 204

    def test_with_bearer_auth(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            auth = request.headers.get("Authorization", "")
            return httpx.Response(200, json={"auth": auth})

        transport = httpx.MockTransport(handler)
        with ApiClient(
            "https://api.example.com", auth=BearerAuth("test-token")
        ) as client:
            client._client = httpx.Client(
                base_url="https://api.example.com",
                transport=transport,
                auth=BearerAuth("test-token"),
            )
            resp = client.get("/me")
            assert resp.json()["auth"] == "Bearer test-token"

    def test_with_middleware(self) -> None:
        call_log: list[str] = []

        class LogMiddleware:
            def process_request(self, request: httpx.Request) -> httpx.Request:
                call_log.append("request")
                return request

            def process_response(self, response: httpx.Response) -> httpx.Response:
                call_log.append("response")
                return response

        transport = httpx.MockTransport(
            lambda req: httpx.Response(200)
        )
        with ApiClient(
            "https://api.example.com", middlewares=[LogMiddleware()]
        ) as client:
            client._client = httpx.Client(
                base_url="https://api.example.com", transport=transport
            )
            client.get("/test")
            assert call_log == ["request", "response"]

    def test_retry_middleware(self) -> None:
        attempt = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal attempt
            attempt += 1
            if attempt < 3:
                return httpx.Response(503)
            return httpx.Response(200, json={"ok": True})

        transport = httpx.MockTransport(handler)
        retry_mw = RetryMiddleware(max_retries=3, delay=0.0)
        with ApiClient(
            "https://api.example.com", middlewares=[retry_mw]
        ) as client:
            client._client = httpx.Client(
                base_url="https://api.example.com", transport=transport
            )
            resp = client.get("/test")
            assert resp.status_code == 200
            assert attempt == 3

    def test_retry_exhausted(self) -> None:
        transport = httpx.MockTransport(
            lambda req: httpx.Response(503)
        )
        retry_mw = RetryMiddleware(max_retries=2, delay=0.0)
        with ApiClient(
            "https://api.example.com", middlewares=[retry_mw]
        ) as client:
            client._client = httpx.Client(
                base_url="https://api.example.com", transport=transport
            )
            resp = client.get("/test")
            assert resp.status_code == 503

    def test_paginate_cursor(self) -> None:
        page = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal page
            page += 1
            if page == 1:
                return httpx.Response(
                    200, json={"results": [1, 2], "next_cursor": "abc"}
                )
            return httpx.Response(200, json={"results": [3], "next_cursor": None})

        transport = httpx.MockTransport(handler)
        with ApiClient("https://api.example.com") as client:
            client._client = httpx.Client(
                base_url="https://api.example.com", transport=transport
            )
            all_results: list[Any] = []
            for batch in client.paginate("/items", CursorPaginator()):
                all_results.extend(batch)
            assert all_results == [1, 2, 3]

    def test_paginate_empty(self) -> None:
        transport = httpx.MockTransport(
            lambda req: httpx.Response(
                200, json={"results": [], "next_cursor": None}
            )
        )
        with ApiClient("https://api.example.com") as client:
            client._client = httpx.Client(
                base_url="https://api.example.com", transport=transport
            )
            pages = list(client.paginate("/items", CursorPaginator()))
            assert pages == []
