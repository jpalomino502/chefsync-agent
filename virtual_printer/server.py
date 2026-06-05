import os
import socketserver
from datetime import datetime


def _read_until_newline(conn):
    buf = b""
    while True:
        b = conn.recv(1)
        if not b:
            break
        buf += b
        if b == b"\n":
            break
    return buf


def _read_exact(conn, n):
    buf = b""
    remaining = n
    while remaining > 0:
        chunk = conn.recv(min(65536, remaining))
        if not chunk:
            break
        buf += chunk
        remaining -= len(chunk)
    return buf


def _save_job(jobs_dir, control_bytes, data_bytes):
    os.makedirs(jobs_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    base = os.path.join(jobs_dir, f"job-{ts}")
    if control_bytes:
        with open(base + ".ctl", "wb") as handle:
            handle.write(control_bytes)
    with open(base + ".prn", "wb") as handle:
        handle.write(data_bytes)
    return base


def job_bases(jobs_dir):
    os.makedirs(jobs_dir, exist_ok=True)
    items = []
    for name in os.listdir(jobs_dir):
        if name.endswith(".prn"):
            base = os.path.join(jobs_dir, name[:-4])
            try:
                mtime = os.path.getmtime(base + ".prn")
            except Exception:
                mtime = 0
            items.append((mtime, base))
    items.sort(reverse=True)
    return [base for _, base in items]


def read_prn_text(base):
    try:
        with open(base + ".prn", "rb") as handle:
            data = handle.read()
        return data, data.decode("cp437", errors="ignore")
    except Exception:
        return b"", ""


class LPDHandler(socketserver.BaseRequestHandler):
    def handle(self):
        conn = self.request
        try:
            cmd = conn.recv(1)
            if not cmd or cmd[0] != 0x02:
                return
            _ = _read_until_newline(conn)
            conn.sendall(b"\x00")
            control = b""
            data = b""
            while True:
                sub = conn.recv(1)
                if not sub:
                    break
                if sub[0] == 0x02:
                    header = _read_until_newline(conn)
                    parts = header.strip().split()
                    size = int(parts[0]) if parts else 0
                    conn.sendall(b"\x00")
                    control = _read_exact(conn, size)
                    conn.sendall(b"\x00")
                elif sub[0] == 0x03:
                    header = _read_until_newline(conn)
                    parts = header.strip().split()
                    size = int(parts[0]) if parts else 0
                    conn.sendall(b"\x00")
                    if size > 0:
                        chunk = _read_exact(conn, size)
                        data += chunk
                        conn.sendall(b"\x00")
                    else:
                        buf = b""
                        while True:
                            chunk = conn.recv(65536)
                            if not chunk:
                                break
                            idx = chunk.find(b"\x00")
                            if idx != -1:
                                buf += chunk[:idx]
                                data += buf
                                conn.sendall(b"\x00")
                                break
                            buf += chunk
                else:
                    break
            if data:
                _save_job(self.server.jobs_dir, control, data)
        except Exception:
            try:
                conn.sendall(b"\x01")
            except Exception:
                pass


class Raw9100Handler(socketserver.BaseRequestHandler):
    def handle(self):
        conn = self.request
        try:
            conn.settimeout(2.0)
        except Exception:
            pass
        data = b""
        while True:
            try:
                chunk = conn.recv(65536)
            except TimeoutError:
                break
            except ConnectionResetError:
                break
            if not chunk:
                break
            data += chunk
        if data:
            _save_job(self.server.jobs_dir, b"", data)


def serve(host, port, jobs_dir, server_ref=None):
    class _Server(socketserver.ThreadingTCPServer):
        allow_reuse_address = True

        def handle_error(self, request, client_address):
            pass

    server = _Server((host, port), LPDHandler)
    server.jobs_dir = jobs_dir
    server.allow_reuse_address = True
    if server_ref is not None:
        server_ref["server"] = server
    try:
        server.serve_forever()
    except Exception:
        pass
    finally:
        server.server_close()


def serve_raw(host, port, jobs_dir, server_ref=None):
    class _Server(socketserver.ThreadingTCPServer):
        allow_reuse_address = True

        def handle_error(self, request, client_address):
            pass

    server = _Server((host, port), Raw9100Handler)
    server.jobs_dir = jobs_dir
    server.allow_reuse_address = True
    if server_ref is not None:
        server_ref["server"] = server
    try:
        server.serve_forever()
    except Exception:
        pass
    finally:
        server.server_close()
