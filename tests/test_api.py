import asyncio
import unittest
from httpx import ASGITransport, AsyncClient
from app.config import get_settings
from app.main import app


class TestAPIEndpoints(unittest.TestCase):
    """Integration tests for FastAPI endpoints and authentication."""

    def test_health_endpoint(self):
        """Test health check endpoint."""
        async def _run():
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                response = await ac.get("/health")
                self.assertEqual(response.status_code, 200)
                data = response.json()
                self.assertEqual(data["status"], "healthy")

        asyncio.run(_run())

    def test_webhook_unauthorized(self):
        """Test mobile webhook rejects requests with invalid or missing secret key."""
        async def _run():
            payload = {"text": "Spent $20 at Gas Station", "app_name": "Bank"}

            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                # Missing header
                res1 = await ac.post("/webhook/mobile", json=payload)
                self.assertEqual(res1.status_code, 401)

                # Wrong key
                res2 = await ac.post(
                    "/webhook/mobile",
                    json=payload,
                    headers={"x-secret-key": "invalid_wrong_secret"},
                )
                self.assertEqual(res2.status_code, 401)

        asyncio.run(_run())

    def test_webhook_authorized(self):
        """Test mobile webhook accepts valid secret key and extracts amount."""
        async def _run():
            settings = get_settings()
            payload = {"text": "Purchase of $45.20 at Trader Joes", "app_name": "Chase Mobile"}

            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                res = await ac.post(
                    "/webhook/mobile",
                    json=payload,
                    headers={"x-secret-key": settings.WEBHOOK_SECRET},
                )
                self.assertEqual(res.status_code, 200)
                data = res.json()
                self.assertEqual(data["status"], "success")
                self.assertEqual(data["detected_amount"], 45.20)

        asyncio.run(_run())


if __name__ == "__main__":
    unittest.main()
