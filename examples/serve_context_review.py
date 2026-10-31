"""Serve only the generated annotation page on localhost, without write endpoints."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--port", type=int, default=0)
    args = parser.parse_args()
    directory = args.directory.resolve()
    pages = {"/": directory / "review.html", "/review": directory / "review.html",
             "/fixture": directory / "fixture.html"}
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            path = pages.get(self.path.split("?", 1)[0])
            if path is None or not path.is_file():
                self.send_error(404)
                return
            body = path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(json.dumps({"review_url": f"http://127.0.0.1:{server.server_port}/review",
                      "fixture_url": f"http://127.0.0.1:{server.server_port}/fixture"}), flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
