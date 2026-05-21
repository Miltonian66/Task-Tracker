from __future__ import annotations

import pytest


@pytest.mark.asyncio
class TestCreateTask:
    async def test_creates_with_default_status(self, client, sample_task_payload):
        response = await client.post("/tasks", json=sample_task_payload)

        assert response.status_code == 201, response.text
        body = response.json()
        assert body["id"]
        assert body["title"] == sample_task_payload["title"]
        assert body["description"] == sample_task_payload["description"]
        assert body["assignee"] == sample_task_payload["assignee"]
        assert body["status"] == "todo"
        assert body["created_at"]
        assert body["updated_at"]

    async def test_strips_whitespace(self, client):
        response = await client.post(
            "/tasks",
            json={"title": "  Тест  ", "description": "  Описание  ", "assignee": " ivanov "},
        )
        assert response.status_code == 201
        body = response.json()
        assert body["title"] == "Тест"
        assert body["description"] == "Описание"
        assert body["assignee"] == "ivanov"

    async def test_rejects_empty_title(self, client):
        response = await client.post(
            "/tasks",
            json={"title": "   ", "description": "desc", "assignee": "ivanov"},
        )
        assert response.status_code == 422
        body = response.json()
        assert body["error"]["code"] == "validation_error"

    async def test_rejects_missing_assignee(self, client):
        response = await client.post("/tasks", json={"title": "Задача", "description": "desc"})
        assert response.status_code == 422

    async def test_rejects_too_long_title(self, client):
        response = await client.post(
            "/tasks",
            json={"title": "x" * 201, "description": "desc", "assignee": "ivanov"},
        )
        assert response.status_code == 422

    async def test_rejects_missing_description(self, client):
        response = await client.post(
            "/tasks",
            json={"title": "Задача", "assignee": "ivanov"},
        )
        assert response.status_code == 422
        body = response.json()
        assert body["error"]["code"] == "validation_error"

        fields = {tuple(e["loc"]) for e in body["error"]["details"]["errors"]}
        assert ("body", "description") in fields

    async def test_rejects_empty_description(self, client):
        response = await client.post(
            "/tasks",
            json={"title": "Задача", "description": "", "assignee": "ivanov"},
        )
        assert response.status_code == 422

    async def test_rejects_whitespace_only_description(self, client):
        response = await client.post(
            "/tasks",
            json={"title": "Задача", "description": "   ", "assignee": "ivanov"},
        )
        assert response.status_code == 422


@pytest.mark.asyncio
class TestChangeStatus:
    async def _create(self, client, **overrides):
        payload = {
            "title": "Задача",
            "description": "Дефолтное описание для тестов смены статуса",
            "assignee": "ivanov",
            **overrides,
        }
        resp = await client.post("/tasks", json=payload)
        assert resp.status_code == 201
        return resp.json()

    async def test_forward_transition_ok(self, client):
        task = await self._create(client)
        resp = await client.patch(
            f"/tasks/{task['id']}/status",
            json={"status": "in_progress"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "in_progress"

    async def test_full_flow_todo_to_done(self, client):
        task = await self._create(client)
        for new_status in ("in_progress", "review", "done"):
            resp = await client.patch(
                f"/tasks/{task['id']}/status",
                json={"status": new_status},
            )
            assert resp.status_code == 200, resp.text
            assert resp.json()["status"] == new_status

    async def test_skip_step_rejected(self, client):
        task = await self._create(client)
        resp = await client.patch(
            f"/tasks/{task['id']}/status",
            json={"status": "done"},
        )
        assert resp.status_code == 409
        body = resp.json()
        assert body["error"]["code"] == "invalid_status_transition"
        assert body["error"]["details"]["expected"] == "in_progress"

    async def test_cannot_go_back_from_done(self, client):
        task = await self._create(client)

        for s in ("in_progress", "review", "done"):
            await client.patch(f"/tasks/{task['id']}/status", json={"status": s})

        resp = await client.patch(
            f"/tasks/{task['id']}/status",
            json={"status": "in_progress"},
        )
        assert resp.status_code == 409
        body = resp.json()
        assert body["error"]["code"] == "invalid_status_transition"
        assert "завершена" in body["error"]["message"].lower() or "done" in body["error"]["message"]

    async def test_cannot_go_back_from_review(self, client):
        task = await self._create(client)

        await client.patch(f"/tasks/{task['id']}/status", json={"status": "in_progress"})
        await client.patch(f"/tasks/{task['id']}/status", json={"status": "review"})

        resp = await client.patch(
            f"/tasks/{task['id']}/status",
            json={"status": "todo"},
        )
        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "invalid_status_transition"

    async def test_same_status_rejected(self, client):
        task = await self._create(client)
        resp = await client.patch(
            f"/tasks/{task['id']}/status",
            json={"status": "todo"},
        )
        assert resp.status_code == 409

    async def test_unknown_status_rejected(self, client):
        task = await self._create(client)
        resp = await client.patch(
            f"/tasks/{task['id']}/status",
            json={"status": "wat"},
        )
        assert resp.status_code == 422

    async def test_status_change_on_missing_task(self, client):
        resp = await client.patch(
            "/tasks/00000000-0000-0000-0000-000000000000/status",
            json={"status": "in_progress"},
        )
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "task_not_found"


@pytest.mark.asyncio
class TestListAndGet:
    async def test_list_filters_by_status_and_assignee(self, client):
        await client.post("/tasks", json={"title": "A", "description": "d", "assignee": "alice"})
        await client.post("/tasks", json={"title": "B", "description": "d", "assignee": "bob"})
        b_task = (
            await client.post("/tasks", json={"title": "C", "description": "d", "assignee": "bob"})
        ).json()
        await client.patch(
            f"/tasks/{b_task['id']}/status",
            json={"status": "in_progress"},
        )

        # Только Bob.
        resp = await client.get("/tasks", params={"assignee": "bob"})
        assert resp.status_code == 200
        assert {t["title"] for t in resp.json()} == {"B", "C"}

        resp = await client.get("/tasks", params={"status": "in_progress"})
        assert resp.status_code == 200
        titles = [t["title"] for t in resp.json()]
        assert titles == ["C"]

        resp = await client.get("/tasks")
        assert resp.status_code == 200
        assert len(resp.json()) == 3

    async def test_get_by_id(self, client, sample_task_payload):
        created = (await client.post("/tasks", json=sample_task_payload)).json()
        resp = await client.get(f"/tasks/{created['id']}")
        assert resp.status_code == 200
        assert resp.json()["id"] == created["id"]

    async def test_get_unknown_returns_404(self, client):
        resp = await client.get("/tasks/00000000-0000-0000-0000-000000000000")
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "task_not_found"

    async def test_delete(self, client, sample_task_payload):
        created = (await client.post("/tasks", json=sample_task_payload)).json()
        resp = await client.delete(f"/tasks/{created['id']}")
        assert resp.status_code == 204
        assert (await client.get(f"/tasks/{created['id']}")).status_code == 404


@pytest.mark.asyncio
class TestPagination:
    async def test_limit_and_offset(self, client):
        for i in range(5):
            resp = await client.post(
                "/tasks",
                json={"title": f"T{i}", "description": "d", "assignee": "u"},
            )
            assert resp.status_code == 201

        page1 = await client.get("/tasks", params={"limit": 2, "offset": 0})
        page2 = await client.get("/tasks", params={"limit": 2, "offset": 2})
        page3 = await client.get("/tasks", params={"limit": 2, "offset": 4})

        assert [len(r.json()) for r in (page1, page2, page3)] == [2, 2, 1]
        ids = {t["id"] for r in (page1, page2, page3) for t in r.json()}
        assert len(ids) == 5

    async def test_default_limit_applies(self, client):
        resp = await client.get("/tasks")
        assert resp.status_code == 200
        assert len(resp.json()) <= 100

    async def test_invalid_limit_rejected(self, client):
        for bad in ({"limit": 0}, {"limit": -1}, {"offset": -1}):
            resp = await client.get("/tasks", params=bad)
            assert resp.status_code == 422, bad

    async def test_limit_above_max_rejected(self, client):
        resp = await client.get("/tasks", params={"limit": 501})
        assert resp.status_code == 422
        body = resp.json()
        assert body["error"]["code"] == "validation_error"
        fields = {tuple(e["loc"]) for e in body["error"]["details"]["errors"]}
        assert ("query", "limit") in fields

    async def test_limit_at_max_allowed(self, client):
        resp = await client.get("/tasks", params={"limit": 500})
        assert resp.status_code == 200


@pytest.mark.asyncio
class TestCacheVersionInit:
    async def test_read_path_does_not_initialize_version(self):
        """Read-path не должен писать в Redis версионный ключ."""
        import fakeredis.aioredis

        from app.cache import TaskListCache

        fake = fakeredis.aioredis.FakeRedis(decode_responses=False)
        cache = TaskListCache(fake, ttl_seconds=30, enabled=True)

        # Ключ версии умышленно НЕ инициализирован.
        result = await cache.get(status=None, assignee=None, limit=10, offset=0)
        assert result is None  # cache miss

        # И — главное — version key всё ещё отсутствует.
        assert await fake.get("tasks:list:version") is None
        await fake.aclose()

    async def test_invalidate_after_uninitialized_get(self):
        """После cache miss с отсутствующей версией INCR создаёт ключ корректно."""
        import fakeredis.aioredis

        from app.cache import TaskListCache

        fake = fakeredis.aioredis.FakeRedis(decode_responses=False)
        cache = TaskListCache(fake, ttl_seconds=30, enabled=True)

        await cache.get(status=None, assignee=None, limit=10, offset=0)
        await cache.invalidate()
        assert await fake.get("tasks:list:version") == b"1"
        await fake.aclose()


@pytest.mark.asyncio
class TestCacheInvalidation:
    async def test_cache_invalidates_on_create(self, client):
        # Кэш заполняется первым GET, после POST список должен обновиться.
        (await client.get("/tasks")).json()
        await client.post(
            "/tasks", json={"title": "Новая", "description": "d", "assignee": "alice"}
        )
        listed = (await client.get("/tasks")).json()
        assert len(listed) == 1
        assert listed[0]["title"] == "Новая"
