import asyncio
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock
from weakref import WeakValueDictionary

import httpx

from app import database
from app.main import app


class ApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.db = database.initialize(f"sqlite:///{Path(directory.name) / 'app.db'}")
        self.complete = AsyncMock(return_value=("answer", {
            "resolution_source": "LIVE_INFERENCE", "model": "groq/test",
            "key_id": "key_1", "fallback_attempts": 0, "input_tokens": 13, "output_tokens": 4,
        }))
        app.state.db = self.db
        app.state.router = app.state.cache = None
        app.state.locks = WeakValueDictionary()
        app.state.simulate = True
        app.state.complete = self.complete
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test")
        self.addAsyncCleanup(self.client.aclose)

    async def post(self, session="s", message=" hello ", **kwargs):
        return await self.client.post("/chat", json={"session_id": session, "message": message, **kwargs})

    async def test_readiness(self):
        app.state.router = Mock(model_list=[{}, {}])
        app.state.cache = object()
        response = await self.client.get("/health")
        self.assertEqual(response.json(), {"status": "ok", "keys_configured": 2, "cache_enabled": True})
        with sqlite3.connect(self.db) as db:
            db.execute("DROP TABLE messages")
        response = await self.client.get("/health")
        self.assertEqual((response.status_code, response.json()), (503, {"detail": "database unavailable"}))

    async def test_context_prompt_and_order(self):
        await self.post(system_prompt="Be brief")
        response = await self.post(message="Next")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.complete.await_args.args[2], [
            {"role": "system", "content": "Be brief"},
            {"role": "user", "content": "hello"}, {"role": "assistant", "content": "answer"},
            {"role": "user", "content": "Next"},
        ])
        history = (await self.client.get("/sessions/s/messages")).json()["messages"]
        self.assertEqual([row["content"] for row in history], ["hello", "answer", "Next", "answer"])
        self.assertEqual(history[-1]["metadata"], response.json()["metadata"])
        self.assertEqual(set(history[0]), {"role", "content"})
        await self.post(session="other")
        self.assertEqual(len(self.complete.await_args.args[2]), 2)
        self.assertNotEqual(self.complete.await_args.args[2][0]["content"], "Be brief")

    async def test_validation_and_limits(self):
        for session, message in [("", "a"), ("  ", "a"), ("s"*129, "a"), ("s", " "), ("s", "a"*4001)]:
            self.assertEqual((await self.post(session, message)).status_code, 422)
        for content in (b'{}', b'{'):
            response = await self.client.post("/chat", content=content, headers={"Content-Type": "application/json"})
            self.assertEqual(response.status_code, 422)
            self.assertIn("detail", response.json())
        self.complete.assert_not_awaited()
        self.assertEqual((await self.post("s"*128, " " + "a"*4000)).status_code, 200)

    async def test_history_for_encoded_session_id(self):
        self.assertEqual((await self.post("qa/folder")).status_code, 200)
        response = await self.client.get("/sessions/qa%2Ffolder/messages")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["session_id"], "qa/folder")
        self.assertEqual([m["role"] for m in response.json()["messages"]], ["user", "assistant"])

    async def test_provider_failure_is_atomic(self):
        await self.post(system_prompt="Initial")
        before = database.load_session(self.db, "s")
        self.complete.side_effect = RuntimeError("private provider detail")
        response = await self.post(system_prompt="Replace")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"detail": "all providers unavailable"})
        self.assertEqual(before, database.load_session(self.db, "s"))
        await self.post(session="new")
        missing = await self.client.get("/sessions/new/messages")
        self.assertEqual((missing.status_code, missing.json()), (404, {"detail": "session not found"}))

    async def test_concurrent_session_requests(self):
        replies = self.complete.return_value
        async def delayed(*args):
            await asyncio.sleep(0.01)
            return replies
        self.complete.side_effect = delayed
        results = await asyncio.gather(self.post(message="one"), self.post(message="two"))
        self.assertEqual([r.status_code for r in results], [200, 200])
        self.assertEqual([len(call.args[2]) for call in self.complete.await_args_list], [2, 4])

    async def test_failure_switch(self):
        kwargs = {"json": {"session_id": "s", "message": "hello"}, "headers": {"X-Simulate-Failure": "*=403"}}
        self.assertEqual((await self.client.post("/chat", **kwargs)).status_code, 422)
        app.state.simulate = False
        self.assertEqual((await self.client.post("/chat", **kwargs)).status_code, 200)
        self.assertEqual(self.complete.await_args.args[-1], {})

    async def test_sql_write_rollback(self):
        with sqlite3.connect(self.db) as db:
            db.execute("""CREATE TRIGGER fail BEFORE INSERT ON messages WHEN NEW.role = 'assistant'
                          BEGIN SELECT RAISE(ABORT, 'failed insert'); END""")
        self.assertEqual((await self.post(system_prompt="Replace")).status_code, 503)
        self.assertEqual(database.load_session(self.db, "s"), (None, []))
