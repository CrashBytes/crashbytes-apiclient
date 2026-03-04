# crashbytes-apiclient

httpx API client toolkit — pagination, retry, rate limiting, auth refresh, middleware.

## Install

```bash
pip install crashbytes-apiclient
```

## Usage

```python
from crashbytes_apiclient import (
    ApiClient, BearerAuth, RetryMiddleware, CursorPaginator,
)

client = ApiClient(
    base_url="https://api.example.com",
    auth=BearerAuth("your-token"),
    middlewares=[RetryMiddleware(max_retries=3)],
)

# Simple requests
response = client.get("/users")
response = client.post("/users", json={"name": "Alice"})

# Paginated iteration
for batch in client.paginate("/items", CursorPaginator()):
    for item in batch:
        process(item)

client.close()
```

## Features

- **Auth:** `BearerAuth`, `RefreshableAuth` (auto-refresh on 401)
- **Middleware:** `RetryMiddleware`, `RateLimitMiddleware`, custom middleware protocol
- **Pagination:** `CursorPaginator`, `PageNumberPaginator`
- **HTTP Methods:** `.get()`, `.post()`, `.put()`, `.patch()`, `.delete()`
- **Context Manager:** `with ApiClient(...) as client:`

## License

MIT
