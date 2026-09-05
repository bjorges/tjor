"""Header-echo fixture for identity conformance probes: reflects every
received request header back as JSON, so probes inside the cage can see what
actually crossed the proxy boundary."""

import json
from http.server import BaseHTTPRequestHandler, HTTPServer


class Echo(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        body = json.dumps(
            {"headers": {k.lower(): v for k, v in self.headers.items()}}
        ).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # quiet
        pass


if __name__ == "__main__":
    HTTPServer(("0.0.0.0", 8080), Echo).serve_forever()
