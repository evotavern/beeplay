import json
import threading
import time
import unittest
import uuid
from datetime import timedelta
from unittest.mock import patch

from sqlalchemy import select

from app import config, db, events, generation
from app.models import Generation, GenerationAttempt, GenerationEvent, GenerationKey, User, Work, utcnow
import test_http

HTML = '<!doctype html><html><head><title>Bee</title></head><body><button onclick="this.textContent=\'1\'">Play</button><script>let score = 0;</script></body></html>'
DETAILS = dict(title="Honey Hop", category="relax", emoji="🐝", art="art-one", description="Collect honey")
SUCCESS = (200, {"x-ratelimit-remaining-tokens": "1000"}, {"choices": [{"finish_reason": "stop", "message": {"content": HTML}}], "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30}})


class GenerationTests(test_http.HttpTestCase):
    def setUp(self):
        self.worker_patch = patch.object(generation.Worker, "start")
        self.worker_patch.start()
        super().setUp()
        self.keys_patch = patch.object(config, "EVOMAP_KEYS", ("test-key-one", "test-key-two"))
        self.keys_patch.start()
        self.claim()

    def tearDown(self):
        self.keys_patch.stop()
        super().tearDown()
        self.worker_patch.stop()

    def submit(self, **kwargs):
        return self.client.post("/api/generations", json={"prompt": "A bee game", "request_id": str(uuid.uuid4()), **kwargs})

    def run_job(self, id, response=SUCCESS):
        with db.SessionLocal() as session:
            job = session.get(Generation, id)
            job.status = "generating"
            job.timings = json.dumps({"queue_ms": 1})
            session.commit()
        with patch.object(generation, "request_game", return_value=response):
            generation.run_job(id)
        return self.client.get(f"/api/generations/{id}").json()

    def ready_job(self):
        """A generated game whose details were filled in while it generated."""
        response = self.submit()
        self.assertEqual(response.status_code, 202, response.text)
        id = response.json()["id"]
        self.assertEqual(self.client.put(f"/api/generations/{id}/details", json=DETAILS).status_code, 200)
        self.assertEqual(self.run_job(id)["status"], "ready")
        return id

    def playtest(self, id):
        for kind in ("playtest_opened", "playtest_loaded", "playtest_closed"):
            self.assertEqual(self.client.post(f"/api/generations/{id}/events", json={"kind": kind, "elapsed_ms": 100}).status_code, 204)

    def test_details_entered_during_generation_are_kept_and_timed(self):
        id = self.ready_job()
        job = self.client.get("/api/generations/current").json()["job"]
        self.assertEqual(job["id"], id)
        self.assertFalse(job["active"])
        self.assertEqual(job["details"]["title"], "Honey Hop")
        self.assertIn("playable_ms", job["timings"])
        self.assertIn("idle_wait_ms", job["timings"])
        self.assertNotIn("Honey Hop", self.client.get("/").text)

    def test_preview_is_sandboxed_and_not_cached(self):
        preview = self.client.get(f"/api/generations/{self.ready_job()}/preview")
        self.assertEqual(preview.status_code, 200)
        self.assertIn("sandbox allow-scripts", preview.headers["content-security-policy"])
        self.assertEqual(preview.headers["cache-control"], "no-store")

    def test_publish_requires_a_playtest_then_happens_and_alerts_once(self):
        id = self.ready_job()
        self.assertEqual(self.client.post(f"/api/generations/{id}/publish", json=DETAILS).status_code, 409)
        self.playtest(id)
        with patch.object(events, "alert") as alert:
            first = self.client.post(f"/api/generations/{id}/publish", json=DETAILS)
            second = self.client.post(f"/api/generations/{id}/publish", json=DETAILS)
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(first.json(), second.json())
        alert.assert_called_once()
        self.assertIn("Honey Hop", alert.call_args.args[0])
        with db.SessionLocal() as session:
            self.assertEqual(len(session.scalars(select(Work).where(Work.title == "Honey Hop")).all()), 1)
            attempt = session.scalar(select(GenerationAttempt))
            self.assertEqual(json.loads(attempt.usage)["total_tokens"], 30)
            self.assertNotIn("test-key", attempt.key_id)
            kinds = list(session.scalars(select(GenerationEvent.kind).where(GenerationEvent.generation_id == id)))
            self.assertEqual(kinds.count("published"), 1)

    def test_published_game_joins_the_feed_and_social_features(self):
        id = self.ready_job()
        self.playtest(id)
        work_id = self.client.post(f"/api/generations/{id}/publish", json=DETAILS).json()["work_id"]
        self.assertIn("Honey Hop", self.client.get("/").text)
        self.assertEqual(self.client.post(f"/api/works/{work_id}/like", json={"active": True}).json(), {"active": True, "count": 1})
        self.assertEqual(self.client.post(f"/api/works/{work_id}/save", json={"active": True}).status_code, 200)
        self.assertIn("Honey Hop", self.client.get("/discover").text)
        self.assertIn("Honey Hop", self.client.get("/profile?tab=saved").text)

    def test_worker_error_is_logged_and_fails_the_job(self):
        id = self.submit().json()["id"]
        worker = generation.Worker()
        with patch.object(generation, "run_job", side_effect=RuntimeError("boom")), \
                patch("traceback.print_exc"), patch.object(worker.stop, "wait", side_effect=lambda _: worker.stop.set()):
            worker.loop()
        with db.SessionLocal() as session:
            self.assertEqual(session.get(Generation, id).error, "internal_error")
        self.assertIn("generation_worker_error", config.EVENTS_LOG.read_text())
        self.assertNotIn("boom", config.EVENTS_LOG.read_text())

    def test_submission_idempotence_and_one_active_per_identity(self):
        id = str(uuid.uuid4())
        self.assertEqual(self.submit(request_id=id).status_code, 202)
        self.assertEqual(self.submit(request_id=id).json()["id"], id)
        self.assertEqual(self.submit().status_code, 409)

    def test_another_claim_cannot_access_a_job_or_preview(self):
        id = self.submit().json()["id"]
        self.run_job(id)
        self.claim("bee-3")
        self.assertEqual(self.client.get(f"/api/generations/{id}").status_code, 404)
        self.assertEqual(self.client.get(f"/api/generations/{id}/preview").status_code, 404)
        self.assertIsNone(self.client.get("/api/generations/current").json()["job"])
        self.claim("bee-2")
        # Same random profile, newly issued claim: old drafts remain private.
        self.assertEqual(self.client.get(f"/api/generations/{id}").status_code, 404)

    def test_auth_origin_and_input_guards(self):
        self.assertEqual(self.submit(prompt="   ").status_code, 422)
        self.assertEqual(self.client.post("/api/generations", headers={"Origin": "https://evil.example"}, json={"prompt": "x", "request_id": str(uuid.uuid4())}).status_code, 403)
        self.client.cookies.clear()
        self.assertEqual(self.submit().status_code, 401)

    def test_no_keys_is_explicitly_unavailable(self):
        with patch.object(config, "EVOMAP_KEYS", ()):
            self.assertEqual(self.submit().status_code, 503)

    def test_rotation_rate_limit_and_usage_are_persisted(self):
        id = self.submit().json()["id"]
        with patch.object(generation, "request_game", side_effect=[(429, {"retry-after": "120"}, {"error": {"code": "rate_limit_exceeded"}}), SUCCESS]) as request:
            generation.run_job(id)
        self.assertEqual(request.call_count, 2)
        self.assertNotEqual(request.call_args_list[0].args[0], request.call_args_list[1].args[0])
        with db.SessionLocal() as session:
            limited = session.scalar(select(GenerationKey).where(GenerationKey.cooldown_until.is_not(None)))
            self.assertGreater(limited.cooldown_until, utcnow())
            self.assertFalse(limited.disabled)
            self.assertEqual(session.get(Generation, id).status, "ready")

    def test_exhausted_keys_disable_and_pool_failure_is_bounded(self):
        id = self.submit().json()["id"]
        with patch.object(generation, "request_game", return_value=(429, {}, {"error": {"code": "insufficient_quota"}})) as request:
            generation.run_job(id)
        self.assertEqual(request.call_count, 2)
        with db.SessionLocal() as session:
            self.assertTrue(all(key.disabled for key in session.scalars(select(GenerationKey))))
            self.assertEqual(session.get(Generation, id).error, "keys_unavailable")

    def test_connection_error_is_not_automatically_replayed(self):
        id = self.submit().json()["id"]
        with patch.object(generation, "request_game", side_effect=TimeoutError("secret must not reach logs")) as request:
            generation.run_job(id)
        self.assertEqual(request.call_count, 1)
        self.assertNotIn("secret must", config.EVENTS_LOG.read_text())
        self.assertNotIn("test-key", config.EVENTS_LOG.read_text())

    def test_truncated_output_never_becomes_playable(self):
        id = self.submit().json()["id"]
        result = self.run_job(id, (200, {}, {"choices": [{"finish_reason": "length", "message": {"content": HTML}}]}))
        self.assertEqual(result["error"], "invalid_game")
        self.assertEqual(self.client.get(f"/api/generations/{id}/preview").status_code, 409)

    def test_real_worker_picks_queued_job_and_preserves_early_details_timing(self):
        id = self.submit().json()["id"]
        self.client.put(f"/api/generations/{id}/details", json=DETAILS)
        worker = generation.Worker()
        with patch.object(generation, "request_game", return_value=SUCCESS):
            thread = threading.Thread(target=worker.loop)
            thread.start()
            try:
                deadline = time.monotonic() + 3
                while time.monotonic() < deadline:
                    with db.SessionLocal() as session:
                        job = session.get(Generation, id)
                        if job.status == "ready":
                            self.assertIn("details_ms", json.loads(job.timings))
                            self.assertIn("queue_ms", json.loads(job.timings))
                            break
                    time.sleep(.02)
                else:
                    self.fail("worker did not finish")
            finally:
                worker.stop.set()
                thread.join(3)

    def test_restart_marks_inflight_failed_without_replaying_and_keeps_queued(self):
        id = self.submit().json()["id"]
        with db.SessionLocal() as session:
            job = session.get(Generation, id)
            job.status = "generating"
            session.commit()
        self.worker_patch.stop()
        with patch.object(config, "EVOMAP_KEYS", ()), patch.object(generation, "request_game") as request:
            worker = generation.Worker()
            worker.start()
            worker.close()
            request.assert_not_called()
        with db.SessionLocal() as session:
            self.assertEqual(session.get(Generation, id).error, "interrupted")
        self.worker_patch.start()

    def test_incomplete_details_are_saved_but_cannot_publish(self):
        id = self.submit().json()["id"]
        draft = self.client.put(f"/api/generations/{id}/details", json={"title": "Draft"})
        self.assertEqual(draft.status_code, 200)
        self.run_job(id)
        self.client.post(f"/api/generations/{id}/events", json={"kind": "playtest_loaded"})
        self.assertEqual(self.client.post(f"/api/generations/{id}/publish", json={"title": "Draft"}).status_code, 422)

    def test_document_policy_precedes_all_model_code(self):
        document = generation.normalize_html(HTML.replace("<html>", "<script>bad()</script><html>"))
        self.assertLess(document.index("Content-Security-Policy"), document.index("bad()"))
        self.assertIn("beeplay-reporter", document)


if __name__ == "__main__":
    unittest.main()
