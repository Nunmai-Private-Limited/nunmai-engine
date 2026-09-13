"""A minimal OpenAI-compatible model server for the smoke test.

Answers /v1/chat/completions with a fixed reply and echoes which model was asked for, so the test can
prove which model the engine actually routed the turn to.
"""
import json, threading
from http.server import BaseHTTPRequestHandler, HTTPServer

SEEN = []

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def do_GET(self):
        if self.path.rstrip("/").endswith("/models"):
            body = {"object": "list", "data": [{"id": "stub-main", "object": "model"},
                                               {"id": "stub-fast", "object": "model"}]}
            return self._send(body)
        self._send({"ok": True})

    def do_POST(self):
        n = int(self.headers.get("content-length") or 0)
        req = json.loads(self.rfile.read(n) or b"{}")
        SEEN.append(req)
        model = req.get("model") or "stub-main"
        if req.get("stream"):
            return self._send_stream(model)
        self._send({
            "id": "chatcmpl-stub", "object": "chat.completion", "created": 0, "model": model,
            "choices": [{"index": 0, "message": {"role": "assistant",
                        "content": f"pong from {model}"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 11, "completion_tokens": 3, "total_tokens": 14},
        })

    def _send_stream(self, model):
        """The engine asks for SSE; answer in OpenAI chunk shape and finish cleanly."""
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.end_headers()
        base = {"id": "chatcmpl-stub", "object": "chat.completion.chunk", "created": 0, "model": model}
        def frame(delta, finish=None, usage=None):
            payload = {**base, "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}
            if usage: payload["usage"] = usage
            self.wfile.write(f"data: {json.dumps(payload)}\n\n".encode()); self.wfile.flush()
        frame({"role": "assistant"})
        frame({"content": f"pong from {model}"})
        frame({}, "stop", {"prompt_tokens": 11, "completion_tokens": 3, "total_tokens": 14})
        self.wfile.write(b"data: [DONE]\n\n"); self.wfile.flush()

    def _send(self, body):
        raw = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

if __name__ == "__main__":
    import sys
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8931
    srv = HTTPServer(("127.0.0.1", port), H)
    print(f"stub model server on {port}", flush=True)
    srv.serve_forever()
