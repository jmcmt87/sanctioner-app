from __future__ import annotations


async def test_health_returns_200(client):
    response = await client.get("/health")
    assert response.status_code == 200


async def test_health_response_body(client):
    response = await client.get("/health")
    data = response.json()
    assert data == {"status": "ok"}
