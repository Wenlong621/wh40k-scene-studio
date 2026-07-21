"""静态服务器 + 截图保存接口（POST /save?name=xxx，body 为 dataURL）"""
import http.server
import socketserver
import base64
import os

ROOT = os.path.dirname(os.path.abspath(__file__))
PORT = 8943


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=ROOT, **kwargs)

    def end_headers(self):
        # 强制浏览器每次校验 mtime（换模型/改文件后能立即生效，未改则走 304 很快）
        self.send_header('Cache-Control', 'no-cache, must-revalidate')
        super().end_headers()

    def do_POST(self):
        if self.path.startswith('/layout'):
            # 浏览器 localStorage(wh40k_*) 自动落盘：body 为 JSON 全量快照，存 layouts/<name>.json
            length = int(self.headers.get('Content-Length', 0))
            data = self.rfile.read(length)
            name = 'backup'
            if 'name=' in self.path:
                name = ''.join(c for c in self.path.split('name=')[-1] if c.isalnum() or c in '-_') or 'backup'
            out_dir = os.path.join(ROOT, 'layouts')
            os.makedirs(out_dir, exist_ok=True)
            with open(os.path.join(out_dir, name + '.json'), 'wb') as f:
                f.write(data)
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'ok')
            return
        if self.path.startswith('/save'):
            length = int(self.headers.get('Content-Length', 0))
            data = self.rfile.read(length)
            try:
                raw = base64.b64decode(data.split(b',', 1)[1])
                name = 'shot'
                if 'name=' in self.path:
                    name = ''.join(c for c in self.path.split('name=')[-1] if c.isalnum() or c in '-_')
                out_dir = os.path.join(ROOT, '_verify')
                os.makedirs(out_dir, exist_ok=True)
                with open(os.path.join(out_dir, name + '.jpg'), 'wb') as f:
                    f.write(raw)
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'saved')
            except Exception as e:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(str(e).encode())
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *args):
        pass


class ThreadingServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


with ThreadingServer(('127.0.0.1', PORT), Handler) as srv:
    print(f'serving on {PORT}')
    srv.serve_forever()
