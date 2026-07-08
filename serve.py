import http.server
import os
import socketserver

PORT = 9080
os.chdir(os.path.join(os.path.dirname(__file__), "site"))

with socketserver.TCPServer(("", PORT), http.server.SimpleHTTPRequestHandler) as httpd:
    print(f"Serving site/ at http://localhost:{PORT}")
    httpd.serve_forever()
