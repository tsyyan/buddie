"""client.py's retries (no network): a short 429 waits and sends the same request again."""
from __future__ import annotations

import email.message
import io
import json
import sys
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
import client as cl  # noqa: E402


class Reply(io.BytesIO):
    status = 200
    headers = {"Content-Type": "application/json"}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def limited(after: str) -> urllib.error.HTTPError:
    headers = email.message.Message()
    headers["Retry-After"] = after
    return urllib.error.HTTPError("https://x", 429, "Too Many Requests", headers,
                                  io.BytesIO(b'{"error":{"message":"Rate limit reached on tokens per minute"}}'))


class ShortRateLimit(unittest.TestCase):
    def test_a_short_429_is_waited_out_and_the_same_request_sent_again(self):
        """BDX-004: the 429 body overwrote the request body, so the retry failed with 'bytes is not JSON
        serializable' and the unit was recorded as a failed run."""
        ok = json.dumps({"choices": [{"message": {"content": "hi"}}], "usage": {}}).encode()
        sent = []

        def urlopen(req, timeout):
            sent.append(json.loads(req.data))
            if len(sent) == 1:
                raise limited("1")
            return Reply(ok)

        with mock.patch.dict("os.environ", {"GROQ_API_KEY": "k"}), \
                mock.patch.object(cl.urllib.request, "urlopen", urlopen), mock.patch.object(cl.time, "sleep"):
            c = cl.Client("groq", "openai/gpt-oss-120b", 60, 10, 30, None)
            msg, _ = c.chat([{"role": "user", "content": "q"}], None)
        self.assertEqual(msg["content"], "hi")
        self.assertEqual(len(sent), 2)
        self.assertEqual(sent[0], sent[1])

    def test_a_long_429_stops_the_provider(self):
        def urlopen(req, timeout):
            raise limited("3600")

        with mock.patch.dict("os.environ", {"GROQ_API_KEY": "k"}), \
                mock.patch.object(cl.urllib.request, "urlopen", urlopen), mock.patch.object(cl.time, "sleep"):
            c = cl.Client("groq", "openai/gpt-oss-120b", 60, 10, 30, None)
            with self.assertRaises(cl.Stop):
                c.chat([{"role": "user", "content": "q"}], None)


if __name__ == "__main__":
    unittest.main()
