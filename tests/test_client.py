import uuid

import httpx
import pytest
import respx


class TestDualEntryClient:
    def test_sets_api_key_header(self):
        from dualentry_cli.client import DualEntryClient

        client = DualEntryClient(api_url="https://api.dualentry.com", api_key="org_live_xxxx_secret")
        assert client._client.headers["X-API-KEY"] == "org_live_xxxx_secret"

    def test_sets_user_agent_header(self):
        from dualentry_cli import USER_AGENT
        from dualentry_cli.client import DualEntryClient

        client = DualEntryClient(api_url="https://api.dualentry.com", api_key="test_key")
        assert client._client.headers["User-Agent"] == USER_AGENT

    @respx.mock
    def test_get_request(self):
        from dualentry_cli.client import DualEntryClient

        route = respx.get("https://api.dualentry.com/public/v2/invoices/").mock(return_value=httpx.Response(200, json={"items": [], "count": 0}))
        client = DualEntryClient(api_url="https://api.dualentry.com", api_key="test_key")
        data = client.get("/invoices/")
        assert data == {"items": [], "count": 0}
        assert route.called

    @respx.mock
    def test_post_request(self):
        from dualentry_cli.client import DualEntryClient

        respx.post("https://api.dualentry.com/public/v2/invoices/").mock(return_value=httpx.Response(201, json={"id": 1, "number": "INV-001"}))
        client = DualEntryClient(api_url="https://api.dualentry.com", api_key="test_key")
        data = client.post("/invoices/", json={"customer_id": 1})
        assert data == {"id": 1, "number": "INV-001"}

    @respx.mock
    def test_handles_error_response(self):
        from dualentry_cli.client import APIError, DualEntryClient

        respx.get("https://api.dualentry.com/public/v2/invoices/").mock(return_value=httpx.Response(403, json={"success": False, "errors": {"__all__": ["Access denied"]}}))
        client = DualEntryClient(api_url="https://api.dualentry.com", api_key="test_key")
        with pytest.raises(APIError, match="403"):
            client.get("/invoices/")

    def test_from_env_uses_api_key_env_var(self, monkeypatch):
        from dualentry_cli.client import DualEntryClient

        monkeypatch.setenv("X_API_KEY", "env_key_123")
        client = DualEntryClient.from_env(api_url="https://api.dualentry.com")
        assert client._client.headers["X-API-KEY"] == "env_key_123"


class TestErrorMessages:
    """Test that error responses produce helpful messages."""

    @respx.mock
    def test_401_suggests_login(self):
        from dualentry_cli.client import APIError, DualEntryClient

        respx.get("https://api.dualentry.com/public/v2/test/").mock(return_value=httpx.Response(401, json={"error": "unauthorized"}))
        client = DualEntryClient(api_url="https://api.dualentry.com", api_key="bad_key")
        with pytest.raises(APIError) as exc:
            client.get("/test/")
        assert "dualentry auth login" in exc.value.detail

    @respx.mock
    def test_404_says_not_found(self):
        from dualentry_cli.client import APIError, DualEntryClient

        respx.get("https://api.dualentry.com/public/v2/invoices/999/").mock(return_value=httpx.Response(404, json={"error": "not found"}))
        client = DualEntryClient(api_url="https://api.dualentry.com", api_key="test_key")
        with pytest.raises(APIError) as exc:
            client.get("/invoices/999/")
        assert "not found" in exc.value.detail.lower()

    @respx.mock
    def test_422_shows_validation_details(self):
        from dualentry_cli.client import APIError, DualEntryClient

        respx.post("https://api.dualentry.com/public/v2/invoices/").mock(return_value=httpx.Response(422, json={"errors": {"customer_id": ["required"]}}))
        client = DualEntryClient(api_url="https://api.dualentry.com", api_key="test_key")
        with pytest.raises(APIError) as exc:
            client.post("/invoices/", json={})
        assert "validation" in exc.value.detail.lower()
        assert "customer_id" in exc.value.detail

    @respx.mock
    def test_429_says_rate_limited(self):
        from dualentry_cli.client import APIError, DualEntryClient

        respx.get("https://api.dualentry.com/public/v2/invoices/").mock(return_value=httpx.Response(429, json={"error": "too many requests"}))
        client = DualEntryClient(api_url="https://api.dualentry.com", api_key="test_key")
        with pytest.raises(APIError) as exc:
            client.get("/invoices/")
        assert "rate limited" in exc.value.detail.lower()

    @respx.mock
    def test_500_says_server_error(self):
        from dualentry_cli.client import APIError, DualEntryClient

        respx.get("https://api.dualentry.com/public/v2/invoices/").mock(return_value=httpx.Response(500, text="Internal Server Error"))
        client = DualEntryClient(api_url="https://api.dualentry.com", api_key="test_key")
        with pytest.raises(APIError) as exc:
            client.get("/invoices/")
        assert "server error" in exc.value.detail.lower()


class TestContextManager:
    """Test client as context manager."""

    def test_context_manager_closes_client(self):
        from dualentry_cli.client import DualEntryClient

        with DualEntryClient(api_url="https://api.dualentry.com", api_key="test_key") as client:
            assert client._client is not None
        assert client._client.is_closed


class TestIdempotencyKey:
    """
    Writes carry an Idempotency-Key so a retry cannot duplicate a record.

    The API replays the original response for a repeated key rather than running
    the operation again: https://docs.dualentry.com/developers/release-notes/2026-08-12
    """

    BASE = "https://api.dualentry.com/public/v2"

    @pytest.fixture
    def no_backoff(self, monkeypatch):
        """Collapse the retry backoff so retry tests stay fast."""
        monkeypatch.setattr("dualentry_cli.client._RETRY_DELAYS", [0, 0, 0])

    @staticmethod
    def _client(*, retry=False):
        from dualentry_cli.client import DualEntryClient

        return DualEntryClient(api_url="https://api.dualentry.com", api_key="test_key", retry=retry)

    @pytest.mark.parametrize(
        ("method", "call"),
        [
            ("post", lambda c: c.post("/invoices/", json={"customer_id": 1})),
            ("put", lambda c: c.put("/invoices/1/", json={"memo": "x"})),
            ("patch", lambda c: c.patch("/customer-payments/1/", json={"memo": "x"})),
            ("delete", lambda c: c.delete("/invoices/1/")),
        ],
    )
    @respx.mock
    def test_write_methods_send_an_idempotency_key(self, method, call):
        route = getattr(respx, method)(url__startswith=self.BASE).mock(return_value=httpx.Response(200, json={"ok": True}))

        call(self._client())

        key = route.calls[0].request.headers.get("Idempotency-Key")
        assert key is not None, f"{method.upper()} must send an Idempotency-Key"
        # Documented as "a unique value (a UUID works well)", max length 255.
        assert uuid.UUID(key)
        assert len(key) <= 255

    @respx.mock
    def test_get_does_not_send_an_idempotency_key(self):
        route = respx.get(f"{self.BASE}/invoices/").mock(return_value=httpx.Response(200, json={"items": [], "count": 0}))

        self._client().get("/invoices/")

        assert "Idempotency-Key" not in route.calls[0].request.headers

    @pytest.mark.usefixtures("no_backoff")
    @respx.mock
    def test_retry_reuses_the_same_key_across_attempts(self):
        """The whole point: a retried POST must not create a second record."""
        route = respx.post(f"{self.BASE}/invoices/").mock(
            side_effect=[
                httpx.Response(502, text="bad gateway"),
                httpx.Response(201, json={"internal_id": 1}),
            ]
        )

        data = self._client(retry=True).post("/invoices/", json={"customer_id": 1})

        assert data == {"internal_id": 1}
        assert route.call_count == 2
        keys = {c.request.headers["Idempotency-Key"] for c in route.calls}
        assert len(keys) == 1, f"retry must reuse the original key, got {keys}"

    @pytest.mark.usefixtures("no_backoff")
    @respx.mock
    def test_every_retry_attempt_carries_the_key(self):
        from dualentry_cli.client import APIError

        route = respx.post(f"{self.BASE}/invoices/").mock(return_value=httpx.Response(502, text="bad gateway"))

        with pytest.raises(APIError):
            self._client(retry=True).post("/invoices/", json={"customer_id": 1})

        # 4, not 3: the loop runs _MAX_RETRIES times and then issues one more
        # request after it. That off-by-one is tracked separately; it is harmless
        # here precisely because every attempt replays the same key.
        assert route.call_count == 4
        keys = {c.request.headers["Idempotency-Key"] for c in route.calls}
        assert len(keys) == 1, f"every attempt must reuse one key, got {keys}"

    @respx.mock
    def test_separate_requests_use_different_keys(self):
        route = respx.post(f"{self.BASE}/invoices/").mock(return_value=httpx.Response(201, json={"internal_id": 1}))
        client = self._client()

        client.post("/invoices/", json={"customer_id": 1})
        client.post("/invoices/", json={"customer_id": 2})

        keys = [c.request.headers["Idempotency-Key"] for c in route.calls]
        assert keys[0] != keys[1], "each logical request needs its own key"

    @respx.mock
    def test_caller_supplied_key_is_not_overwritten(self):
        route = respx.post(f"{self.BASE}/invoices/").mock(return_value=httpx.Response(201, json={"internal_id": 1}))

        self._client()._request("POST", "/invoices/", json={}, headers={"Idempotency-Key": "caller-supplied-key"})

        assert route.calls[0].request.headers["Idempotency-Key"] == "caller-supplied-key"

    @respx.mock
    def test_key_is_sent_even_when_retry_is_disabled(self):
        """Protects against retries outside our control (proxies, user re-runs are new keys)."""
        route = respx.post(f"{self.BASE}/invoices/").mock(return_value=httpx.Response(201, json={"internal_id": 1}))

        self._client(retry=False).post("/invoices/", json={})

        assert "Idempotency-Key" in route.calls[0].request.headers
