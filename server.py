import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
HTML_PATH = ROOT / 'dramatic.html'

state = {
    'isOpen': False,
    'openCount': 0,
}

state_lock = threading.Lock()
listeners = set()


def snapshot():
    with state_lock:
        return {
            'isOpen': bool(state['isOpen']),
            'openCount': int(state['openCount']),
        }


def broadcast():
    payload = json.dumps(snapshot())
    data = ('data: ' + payload + '\n\n').encode('utf-8')
    dead = []

    for listener in list(listeners):
        try:
            listener.write(data)
            listener.flush()
        except Exception:
            dead.append(listener)

    for listener in dead:
        listeners.discard(listener)


def apply_action(action):
    global state

    with state_lock:
        if action == 'open':
            if not state['isOpen']:
                state['openCount'] += 1
                state['isOpen'] = True
        elif action == 'close':
            state['isOpen'] = False
        elif action == 'reset':
            state['isOpen'] = False
            state['openCount'] = 0
        else:
            return False

    broadcast()
    return True


class DoorHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        return

    def do_GET(self):
        path = self.path.split('?', 1)[0]

        if path == '/api/state':
            self.send_json(snapshot())
            return

        if path == '/events':
            self.send_event_stream()
            return

        if path in ('/', '/index.html'):
            self.serve_file(HTML_PATH)
            return

        file_path = self.resolve_asset(path)
        if file_path is not None:
            self.serve_file(file_path)
            return

        self.send_error(404, 'Not found')

    def do_POST(self):
        path = self.path.split('?', 1)[0]

        if path == '/api/action':
            try:
                length = int(self.headers.get('Content-Length', '0'))
                body = self.rfile.read(length)
                payload = json.loads(body.decode('utf-8'))
                action = payload.get('action', '')
                if apply_action(action):
                    self.send_json({'ok': True, 'state': snapshot()})
                    return
                self.send_json({'ok': False, 'error': 'invalid_action'}, status=400)
                return
            except Exception:
                self.send_json({'ok': False, 'error': 'invalid_request'}, status=400)
                return

        self.send_error(404, 'Not found')

    def send_json(self, payload, status=200):
        body = json.dumps(payload).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def serve_file(self, file_path: Path):
        try:
            data = file_path.read_bytes()
        except FileNotFoundError:
            self.send_error(404, 'File not found')
            return

        self.send_response(200)
        if file_path.suffix.lower() == '.html':
            self.send_header('Content-Type', 'text/html; charset=utf-8')
        elif file_path.suffix.lower() in {'.mp3', '.mpeg'}:
            self.send_header('Content-Type', 'audio/mpeg')
        else:
            self.send_header('Content-Type', 'application/octet-stream')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def resolve_asset(self, path):
        if path.startswith('/'):
            clean = path[1:]
        else:
            clean = path

        candidate = (ROOT / clean).resolve()
        try:
            candidate.relative_to(ROOT.resolve())
        except ValueError:
            return None

        if candidate.is_file():
            return candidate

        # Handle the weird duplicated extensions in the original project files.
        if not candidate.suffix:
            for suffix in ('.mp3', '.mpeg'):
                fallback = candidate.with_suffix(suffix)
                if fallback.is_file():
                    return fallback

        return None

    def send_event_stream(self):
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream')
        self.send_header('Cache-Control', 'no-cache, no-transform')
        self.send_header('Connection', 'keep-alive')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()

        listeners.add(self.wfile)
        try:
            self.wfile.write(('data: ' + json.dumps(snapshot()) + '\n\n').encode('utf-8'))
            self.wfile.flush()
            while True:
                time.sleep(30)
                self.wfile.write(b': heartbeat\n\n')
                self.wfile.flush()
        except Exception:
            pass
        finally:
            listeners.discard(self.wfile)


if __name__ == '__main__':
    host = '0.0.0.0'
    port = 8000
    print(f'Serving Dramatic Door on http://{host}:{port}')
    print('Open the page from any device on the same network using your PC IP address.')
    ThreadingHTTPServer((host, port), DoorHandler).serve_forever()
