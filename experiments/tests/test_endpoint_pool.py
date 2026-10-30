"""Model-free tests of experiments/endpoint_pool.py: a virtual clock and a scripted transport, no network.

    python -m unittest discover -s experiments/tests -v
"""
from __future__ import annotations

import json
import sys
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import endpoint_pool as ep_mod  # noqa: E402
from endpoint_pool import Endpoint, EndpointClient, Pace, Pool, Spent, seconds  # noqa: E402


class Clock:
    """Virtual time: sleep() moves it forward; shared by threads."""

    def __init__(self):
        self.t, self.lock, self.slept = 1000.0, threading.Lock(), []

    def __call__(self) -> float:
        with self.lock:
            return self.t

    def sleep(self, dt: float) -> None:
        with self.lock:
            self.slept.append(dt)
            self.t += max(0.0, dt)


def ok(content="done", tokens=100, headers=None):
    body = {"choices": [{"message": {"role": "assistant", "content": content}}],
            "usage": {"prompt_tokens": tokens, "completion_tokens": 0}}
    return 200, headers or {}, json.dumps(body).encode()


class Script:
    """send(): per-url queues of replies; when a queue is empty the default reply is used. Records calls."""

    def __init__(self, default=None, **replies):
        self.replies = {k: list(v) for k, v in replies.items()}
        self.default, self.calls, self.lock = default or ok(), [], threading.Lock()

    def __call__(self, url, headers, body):
        name = next((k for k in self.replies if k in url), url)
        with self.lock:
            self.calls.append((name, headers, body))
            q = self.replies.get(name)
            reply = q.pop(0) if q else self.default
        if isinstance(reply, Exception):
            raise reply
        return reply


A = Endpoint("a", "https://a.example/v1/chat/completions", None, {"m": "a-model"}, rpm=60)
B = Endpoint("b", "https://b.example/v1/chat/completions", "B_KEY", rpm=60)


class Durations(unittest.TestCase):
    def test_seconds(self):
        self.assertEqual(seconds("7.5s"), 7.5)
        self.assertEqual(seconds("2m30s"), 150)
        self.assertEqual(seconds("1h"), 3600)
        self.assertEqual(seconds("250ms"), 0.25)
        self.assertEqual(seconds("12"), 12)
        self.assertIsNone(seconds(None))
        self.assertIsNone(seconds("soon"))


class Paces(unittest.TestCase):
    def test_requests_a_minute(self):
        c = Clock()
        p = Pace(Endpoint("x", "u", rpm=2), clock=c, sleep=c.sleep)
        p.acquire()
        p.acquire()
        self.assertAlmostEqual(sum(c.slept), 30)  # 2 a minute: the second waits 30 s

    def test_tokens_a_minute(self):
        c = Clock()
        p = Pace(Endpoint("x", "u", tpm=1000), clock=c, sleep=c.sleep)
        p.acquire()
        p.done({"prompt_tokens": 900}, {}, 1.0)
        p.acquire()  # 900 used + about 1,780 expected > 1,000: waits for the minute to pass
        self.assertGreaterEqual(sum(c.slept), 60)

    def test_429_halves_the_rate_and_waits_as_asked(self):
        c = Clock()
        p = Pace(Endpoint("x", "u", rpm=60), clock=c, sleep=c.sleep)
        p.acquire()
        p.throttled(10)
        self.assertEqual(p.rate, 30)
        t0 = c()
        p.acquire()
        self.assertGreaterEqual(c() - t0, 10)
        p.done({}, {}, 0.1)
        self.assertGreater(p.rate, 30)  # climbs back on success

    def test_a_long_retry_spends_until_then(self):
        c = Clock()
        p = Pace(Endpoint("x", "u"), clock=c, sleep=c.sleep, max_wait=300)
        with self.assertRaises(Spent) as e:
            p.throttled(3600)
        self.assertAlmostEqual(e.exception.until, c() + 3600)
        with self.assertRaises(Spent):
            p.acquire()
        c.sleep(3601)
        self.assertTrue(p.revive())
        p.acquire()

    def test_headers_hold_the_next_request(self):
        c = Clock()
        p = Pace(Endpoint("x", "u"), clock=c, sleep=c.sleep)
        p.acquire()
        p.done({"prompt_tokens": 10}, {"x-ratelimit-remaining-tokens": "0", "x-ratelimit-reset-tokens": "7.5s"}, 0.1)
        t0 = c()
        p.acquire()
        self.assertAlmostEqual(c() - t0, 7.5)

    def test_daily_limits(self):
        c = Clock()
        p = Pace(Endpoint("x", "u", rpd=2), clock=c, sleep=c.sleep)
        p.acquire()
        p.acquire()
        with self.assertRaises(Spent) as e:
            p.acquire()
        self.assertIn("daily", str(e.exception))
        self.assertIsNotNone(e.exception.until)

    def test_circuit_breaker(self):
        c = Clock()
        p = Pace(Endpoint("x", "u"), clock=c, sleep=c.sleep, breaker=3, cooldown=120)
        p.failed()
        p.failed()
        with self.assertRaises(Spent) as e:
            p.failed()
        self.assertAlmostEqual(e.exception.until, c() + 120)


class Client(unittest.TestCase):
    def test_model_id_key_and_a_429_then_an_answer(self):
        c = Clock()
        send = Script(a=[(429, {"retry-after": "3"}, b"slow down"), ok("hello")])
        cl = EndpointClient(A, "m", Pace(A, clock=c, sleep=c.sleep), send=send, environ={})
        msg, usage = cl.chat([{"role": "user", "content": "hi"}], None)
        self.assertEqual(msg["content"], "hello")
        self.assertEqual(send.calls[0][2]["model"], "a-model")
        self.assertNotIn("Authorization", send.calls[0][1])  # an anonymous endpoint
        self.assertGreaterEqual(sum(c.slept), 3)

    def test_a_key_is_required_where_named(self):
        with self.assertRaises(Spent):
            EndpointClient(B, "m", Pace(B), environ={})
        cl = EndpointClient(B, "m", Pace(B), environ={"B_KEY": "k"})
        self.assertEqual((cl.key, cl.model), ("k", "m"))

    def test_url_from_the_environment(self):
        cf = ep_mod.REGISTRY["cloudflare"]
        with self.assertRaises(Spent):
            cf.resolve({"CLOUDFLARE_API_TOKEN": "t"})
        url, key = cf.resolve({"CLOUDFLARE_API_TOKEN": "t", "CLOUDFLARE_ACCOUNT_ID": "acc"})
        self.assertIn("/accounts/acc/", url)
        self.assertEqual(cf.model_ids["openai/gpt-oss-120b"], "@cf/openai/gpt-oss-120b")

    def test_extra_body_pins_a_gateway_backend(self):
        ep = ep_mod.REGISTRY["vercel-baseten"]
        send = Script()
        cl = EndpointClient(ep, "openai/gpt-oss-120b", Pace(ep), send=send, environ={"AI_GATEWAY_API_KEY": "k"})
        cl.chat([], None)
        body = send.calls[0][2]
        self.assertEqual(body["model"], "openai/gpt-oss-120b")
        self.assertEqual(body["providerOptions"], {"gateway": {"only": ["baseten"]}})

    def test_an_account_refusal_spends_the_endpoint(self):
        for status in (401, 402, 403):
            send = Script(a=[(status, {}, b"customer_verification_required")])
            pace = Pace(A)
            cl = EndpointClient(A, "m", pace, send=send, environ={})
            with self.assertRaises(Spent):
                cl.chat([], None)
            with self.assertRaises(Spent):
                pace.acquire()

    def test_a_4xx_is_an_error_not_a_retry(self):
        send = Script(a=[(400, {}, b"bad request")])
        cl = EndpointClient(A, "m", Pace(A), send=send, environ={})
        with self.assertRaises(ep_mod.TransportError):
            cl.chat([], None)


class Pools(unittest.TestCase):
    def _jobs(self, n):
        return [{"id": f"J{i}", "steps": 2, "done": []} for i in range(n)]

    def _work(self, rows, lock, b_started=None):
        def work(job, client, name):
            if name == "a" and b_started is not None:
                b_started.wait(5)  # let b take a job first, so the test does not depend on thread timing
            while len(job["done"]) < job["steps"]:
                try:
                    client.chat([{"role": "user", "content": job["id"]}], None)
                finally:
                    if name == "b" and b_started is not None:
                        b_started.set()
                with lock:
                    job["done"].append(name)
                    rows.append((job["id"], name))
        return work

    def _split(self, rows):
        per_job = {}
        for j, name in rows:
            per_job.setdefault(j, set()).add(name)
        return per_job

    def test_a_job_spent_midway_waits_for_its_endpoint(self):
        c = Clock()
        send = Script(b=[ok(), (429, {"retry-after": "86400"}, b"daily")])  # b: one answer, then tomorrow
        pool = Pool([A, B], "m", clock=c, sleep=c.sleep, send=send, environ={"B_KEY": "k"}, log=lambda *_: None)
        jobs, rows, lock = self._jobs(6), [], threading.Lock()
        out = pool.run(jobs, self._work(rows, lock, threading.Event()), started=lambda j: bool(j["done"]),
                       key=lambda j: j["id"], deadline=c() + 3600)
        self.assertTrue(all(len(v) == 1 for v in self._split(rows).values()), rows)
        half = [j["id"] for j in jobs if len(j["done"]) == 1]
        self.assertEqual(len(half), 1)
        self.assertEqual((out["left"], out["pinned"][half[0]]), (half, "b"))
        self.assertEqual(sum(len(j["done"]) == 2 for j in jobs), 5)
        self.assertIn("retry after", out["endpoints"]["b"]["spent"])

    def test_a_job_not_started_goes_to_another_endpoint(self):
        c = Clock()
        send = Script(b=[ok(), ok(), (429, {"retry-after": "86400"}, b"daily")])  # b: one whole job, then tomorrow
        pool = Pool([A, B], "m", clock=c, sleep=c.sleep, send=send, environ={"B_KEY": "k"}, log=lambda *_: None)
        jobs, rows, lock = self._jobs(6), [], threading.Lock()
        out = pool.run(jobs, self._work(rows, lock, threading.Event()), started=lambda j: bool(j["done"]),
                       key=lambda j: j["id"], deadline=c() + 3600)
        per_job = self._split(rows)
        self.assertTrue(all(len(v) == 1 for v in per_job.values()), rows)
        self.assertEqual(out["left"], [])
        self.assertTrue(all(len(j["done"]) == 2 for j in jobs))
        self.assertEqual(sum(v == {"b"} for v in per_job.values()), 1)

    def test_pinned_jobs_from_an_earlier_run_go_to_their_endpoint(self):
        c = Clock()
        pool = Pool([A, B], "m", clock=c, sleep=c.sleep, send=Script(), environ={"B_KEY": "k"}, log=lambda *_: None)
        jobs, rows, lock = self._jobs(4), [], threading.Lock()
        pool.run(jobs, self._work(rows, lock), started=lambda j: bool(j["done"]), key=lambda j: j["id"],
                 pinned={"J0": "b", "J1": "b"})
        self.assertEqual({n for j, n in rows if j in ("J0", "J1")}, {"b"})
        self.assertTrue(all(len(j["done"]) == 2 for j in jobs))

    def test_an_endpoint_comes_back_after_its_pause(self):
        c = Clock()
        send = Script(b=[ok(), (429, {"retry-after": "600"}, b"wait")])
        pool = Pool([B], "m", clock=c, sleep=c.sleep, send=send, environ={"B_KEY": "k"}, max_wait=300,
                    log=lambda *_: None)
        jobs, rows, lock = self._jobs(2), [], threading.Lock()
        out = pool.run(jobs, self._work(rows, lock), started=lambda j: bool(j["done"]), key=lambda j: j["id"],
                       deadline=c() + 3600)
        self.assertEqual(out["left"], [])
        self.assertTrue(all(len(j["done"]) == 2 for j in jobs))

    def test_an_endpoint_without_its_key_is_left_out(self):
        said = []
        pool = Pool([A, B], "m", send=Script(), environ={}, log=said.append)
        self.assertEqual(list(pool.clients), ["a"])
        self.assertIn("B_KEY", said[0])
        with self.assertRaises(Spent):
            Pool([B], "m", environ={}, log=said.append)


if __name__ == "__main__":
    unittest.main()
