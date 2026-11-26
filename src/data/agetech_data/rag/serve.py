"""Private, single-model KURE query worker. No request/body/access logging."""

from __future__ import annotations

import argparse
import hmac
import json
import math
import os
from http.server import BaseHTTPRequestHandler, HTTPServer

from agetech_data.rag.embedder import DIM, MODEL_ID, KureEmbedder


def handler(embedder, token):
    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(5)

        def log_message(self, *_args):
            pass

        def reply(self, status, data):
            payload = json.dumps(data, ensure_ascii=False, allow_nan=False).encode(
                "utf-8"
            )
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self):
            if self.path == "/health":
                self.reply(200, {"status": "ok", "model": MODEL_ID, "dimension": DIM})
            else:
                self.reply(404, {"error": "not_found"})

        def do_POST(self):
            if self.path != "/embed":
                self.reply(404, {"error": "not_found"})
                return
            actual = self.headers.get("Authorization", "").encode("utf-8")
            if not hmac.compare_digest(actual, ("Bearer " + token).encode("utf-8")):
                self.reply(401, {"error": "unauthorized"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if (
                    not 1 <= length <= 4096
                    or self.headers.get_content_type() != "application/json"
                    or self.headers.get("Transfer-Encoding")
                ):
                    raise ValueError("Invalid body")
                value = json.loads(self.rfile.read(length))
                if (
                    not isinstance(value, dict)
                    or set(value) != {"text", "model"}
                    or value["model"] != MODEL_ID
                ):
                    raise ValueError("Unexpected model")
                query = value["text"]
                if (
                    not isinstance(query, str)
                    or not 1 <= len(query.strip()) <= 500
                    or "\x00" in query
                ):
                    raise ValueError("Invalid query")
                query.encode("utf-8")
            except (ValueError, TypeError, UnicodeError):
                self.reply(422, {"error": "invalid_request"})
                return
            try:
                vector = [float(x) for x in embedder.embed_query(query.strip())]
                if (
                    len(vector) != DIM
                    or any(not math.isfinite(x) for x in vector)
                    or abs(sum(x * x for x in vector) - 1) > 0.002
                ):
                    raise ValueError("Invalid embedding")
            except (RuntimeError, ValueError, OSError, TypeError, OverflowError):
                self.reply(503, {"error": "embedding_unavailable"})
                return
            self.reply(200, {"model": MODEL_ID, "vector": vector})

    return Handler


def create_server(address, embedder, token):
    if not token or len(token) < 32:
        raise ValueError("Set a random RAG_EMBEDDING_TOKEN of at least 32 characters")
    if embedder.model_id != MODEL_ID or embedder.dim != DIM:
        raise ValueError("Only the documented KURE model and revision are supported")
    return HTTPServer(address, handler(embedder, token))


def main():
    parser = argparse.ArgumentParser(
        description="Private KURE-v1 query embedding worker"
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8091)
    parser.add_argument("--threads", type=int, choices=range(1, 5), default=2)
    args = parser.parse_args()
    token = os.environ.get("RAG_EMBEDDING_TOKEN", "")
    if len(token) < 32:
        parser.error("Set RAG_EMBEDDING_TOKEN before starting the worker")
    embedder = KureEmbedder(threads=args.threads)
    # Load once before becoming healthy. No duplicate models in API workers.
    _ = embedder.model
    with create_server((args.host, args.port), embedder, token) as server:
        print("KURE query worker ready", flush=True)
        server.serve_forever()


if __name__ == "__main__":
    main()
