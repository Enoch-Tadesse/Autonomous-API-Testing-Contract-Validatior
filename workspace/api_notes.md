# Restaurant Finder API notes

Errors always use the JSON shape {"error": code, "detail": message}. Invalid query
parameters (missing, wrong type, out of range) return HTTP 400, never 422.

The nearby endpoint returns 5 results per page sorted by distance. distance is a number in meters.

The favorites endpoint needs a bearer token. A missing or wrong token returns HTTP 401.

HTTP 503 means a temporary outage: clients should retry with backoff.
