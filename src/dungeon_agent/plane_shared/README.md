# Plane shared

Infrastructure shared by control and data planes: domain contracts, DynamoDB repositories,
WebSocket connection index + delivery, MicroVM HTTP client, and the HTTP/WS API Gateway adapters.

`http/api_gateway.py` defines `ROUTE_PLANE` — which REST route belongs to which plane.
