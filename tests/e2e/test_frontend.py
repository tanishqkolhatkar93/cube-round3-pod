import asyncio

import httpx

from orchestration.api import app


def test_operations_console_is_served_alongside_api():
    async def check_routes():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            page = await client.get("/")
            script = await client.get("/app.js")
            stylesheet = await client.get("/styles.css")
            health = await client.get("/health")
            missing_workflow = await client.get("/workflows/not-a-workflow")
            create_without_auth = await client.post(
                "/workflows", json={"org_id": "org_demo_alpha", "unit_id": "UNIT-0014"}
            )

        assert page.status_code == 200
        assert "CUBE Operations" in page.text
        assert script.status_code == 200 and "async function request" in script.text
        assert stylesheet.status_code == 200 and "prefers-reduced-motion" in stylesheet.text
        assert health.status_code == 200 and health.json()["status"] == "ok"
        assert missing_workflow.status_code == 401
        assert missing_workflow.json()["detail"] == "authenticated tenant context required"
        assert create_without_auth.status_code == 401
        assert create_without_auth.json()["detail"] == "authenticated tenant context required"

    asyncio.run(check_routes())
