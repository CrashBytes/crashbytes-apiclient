"""httpx API client toolkit — pagination, retry, rate limiting, auth, middleware."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any, Protocol

import httpx

if TYPE_CHECKING:
    from collections.abc import Generator, Iterator


# ── Auth ────────────────────────────────────────────────────────────


class BearerAuth(httpx.Auth):
    """Static bearer token authentication."""

    def __init__(self, token: str) -> None:
        self._token = token

    def auth_flow(
        self, request: httpx.Request
    ) -> Generator[httpx.Request, httpx.Response, None]:
        request.headers["Authorization"] = f"Bearer {self._token}"
        yield request


class RefreshableAuth(httpx.Auth):
    """Bearer auth that refreshes the token when it expires."""

    def __init__(
        self,
        token: str,
        refresh_fn: Any,
        refresh_status: int = 401,
    ) -> None:
        self._token = token
        self._refresh_fn = refresh_fn
        self._refresh_status = refresh_status

    def auth_flow(
        self, request: httpx.Request
    ) -> Generator[httpx.Request, httpx.Response, None]:
        request.headers["Authorization"] = f"Bearer {self._token}"
        response = yield request
        if response.status_code == self._refresh_status:
            self._token = self._refresh_fn()
            request.headers["Authorization"] = f"Bearer {self._token}"
            yield request


# ── Middleware Protocol ─────────────────────────────────────────────


class Middleware(Protocol):
    """Protocol for request/response middleware."""

    def process_request(self, request: httpx.Request) -> httpx.Request:
        """Process the request before sending."""
        ...

    def process_response(self, response: httpx.Response) -> httpx.Response:
        """Process the response after receiving."""
        ...


class RetryMiddleware:
    """Retry failed requests with exponential backoff."""

    def __init__(
        self,
        max_retries: int = 3,
        retry_statuses: tuple[int, ...] = (429, 500, 502, 503, 504),
        delay: float = 0.5,
        backoff: float = 2.0,
    ) -> None:
        self.max_retries = max_retries
        self.retry_statuses = retry_statuses
        self.delay = delay
        self.backoff = backoff

    def process_request(self, request: httpx.Request) -> httpx.Request:
        return request

    def process_response(self, response: httpx.Response) -> httpx.Response:
        return response

    def should_retry(self, response: httpx.Response) -> bool:
        """Check if the response should trigger a retry."""
        return response.status_code in self.retry_statuses


class RateLimitMiddleware:
    """Simple rate limiting between requests."""

    def __init__(self, min_interval: float = 0.1) -> None:
        self._min_interval = min_interval
        self._last_request_time = 0.0

    def process_request(self, request: httpx.Request) -> httpx.Request:
        elapsed = time.monotonic() - self._last_request_time
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        self._last_request_time = time.monotonic()
        return request

    def process_response(self, response: httpx.Response) -> httpx.Response:
        return response


# ── Paginator Protocols ─────────────────────────────────────────────


class CursorPaginator:
    """Extract next-page cursor from response JSON."""

    def __init__(
        self,
        cursor_param: str = "cursor",
        cursor_path: str = "next_cursor",
        results_path: str = "results",
    ) -> None:
        self._cursor_param = cursor_param
        self._cursor_path = cursor_path
        self._results_path = results_path

    def get_results(self, data: dict[str, Any]) -> list[Any]:
        """Extract results from the response data."""
        return data.get(self._results_path, [])  # type: ignore[no-any-return]

    def get_next_params(self, data: dict[str, Any]) -> dict[str, str] | None:
        """Get params for the next page, or None if done."""
        cursor = data.get(self._cursor_path)
        if cursor:
            return {self._cursor_param: str(cursor)}
        return None


class PageNumberPaginator:
    """Page-number-based pagination."""

    def __init__(
        self,
        page_param: str = "page",
        results_path: str = "results",
        total_path: str = "total_pages",
    ) -> None:
        self._page_param = page_param
        self._results_path = results_path
        self._total_path = total_path
        self._current_page = 1

    def get_results(self, data: dict[str, Any]) -> list[Any]:
        """Extract results from the response data."""
        return data.get(self._results_path, [])  # type: ignore[no-any-return]

    def get_next_params(self, data: dict[str, Any]) -> dict[str, str] | None:
        """Get params for the next page, or None if done."""
        total = data.get(self._total_path, 0)
        if self._current_page < int(total):
            self._current_page += 1
            return {self._page_param: str(self._current_page)}
        return None


# ── API Client ──────────────────────────────────────────────────────


class ApiClient:
    """High-level httpx API client with middleware and pagination."""

    def __init__(
        self,
        base_url: str,
        auth: httpx.Auth | None = None,
        middlewares: list[Any] | None = None,
        headers: dict[str, str] | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._auth = auth
        self._middlewares = middlewares or []
        self._client = httpx.Client(
            base_url=self._base_url,
            auth=auth,
            headers=headers or {},
            timeout=timeout,
        )

    def _apply_request_middleware(self, request: httpx.Request) -> httpx.Request:
        for mw in self._middlewares:
            request = mw.process_request(request)
        return request

    def _apply_response_middleware(self, response: httpx.Response) -> httpx.Response:
        for mw in self._middlewares:
            response = mw.process_response(response)
        return response

    def _send_with_retry(self, request: httpx.Request) -> httpx.Response:
        retry_mw = None
        for mw in self._middlewares:
            if isinstance(mw, RetryMiddleware):
                retry_mw = mw
                break

        if retry_mw is None:
            return self._client.send(request)

        delay = retry_mw.delay
        last_response: httpx.Response | None = None
        for attempt in range(retry_mw.max_retries + 1):
            response = self._client.send(request)
            last_response = response
            if not retry_mw.should_retry(response):
                return response
            if attempt < retry_mw.max_retries:
                time.sleep(delay)
                delay *= retry_mw.backoff
        assert last_response is not None
        return last_response

    def request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        """Send an HTTP request."""
        request = self._client.build_request(method, path, **kwargs)
        request = self._apply_request_middleware(request)
        response = self._send_with_retry(request)
        return self._apply_response_middleware(response)

    def get(self, path: str, **kwargs: Any) -> httpx.Response:
        """Send a GET request."""
        return self.request("GET", path, **kwargs)

    def post(self, path: str, **kwargs: Any) -> httpx.Response:
        """Send a POST request."""
        return self.request("POST", path, **kwargs)

    def put(self, path: str, **kwargs: Any) -> httpx.Response:
        """Send a PUT request."""
        return self.request("PUT", path, **kwargs)

    def patch(self, path: str, **kwargs: Any) -> httpx.Response:
        """Send a PATCH request."""
        return self.request("PATCH", path, **kwargs)

    def delete(self, path: str, **kwargs: Any) -> httpx.Response:
        """Send a DELETE request."""
        return self.request("DELETE", path, **kwargs)

    def paginate(
        self,
        path: str,
        paginator: CursorPaginator | PageNumberPaginator,
        **kwargs: Any,
    ) -> Iterator[list[Any]]:
        """Iterate through paginated results."""
        params: dict[str, str] = dict(kwargs.pop("params", {}))
        while True:
            response = self.get(path, params=params, **kwargs)
            response.raise_for_status()
            data = response.json()
            results = paginator.get_results(data)
            if results:
                yield results
            next_params = paginator.get_next_params(data)
            if next_params is None:
                break
            params.update(next_params)

    def close(self) -> None:
        """Close the underlying httpx client."""
        self._client.close()

    def __enter__(self) -> ApiClient:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()
