"""Painel local (HTML) para controlar o meeting_transcriber com um botao.

Sobe um servidor HTTP so com a biblioteca padrao (sem Flask/FastAPI, sem
dependencia extra) em http://127.0.0.1:8765, serve o index.html e expoe uma
API minima (/api/start, /api/stop, /api/status) que liga/desliga o processo
`python -m meeting_transcriber` como subprocesso e guarda o log em memoria
para a pagina exibir ao vivo.

Uso: python webui.py   (ou clique duplo em iniciar.bat, que ja prepara o
ambiente virtual antes de chamar isto aqui).
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
import webbrowser
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
PORT = 8765

state_lock = threading.Lock()
state = {
    "proc": None,
    "log": deque(maxlen=1000),
    "output": None,
    "started_at": None,
    "finished_at": None,
    "exit_code": None,
}


def _log(line: str) -> None:
    with state_lock:
        state["log"].append(line.rstrip("\n"))


def _reader_thread(proc: subprocess.Popen) -> None:
    assert proc.stdout is not None
    for raw_line in proc.stdout:
        _log(raw_line)
    exit_code = proc.wait()
    with state_lock:
        state["finished_at"] = time.time()
        state["exit_code"] = exit_code
        state["proc"] = None
    _log(f"[painel] processo encerrado (codigo {exit_code}).")


def start_transcriber(opts: dict) -> tuple[bool, str]:
    with state_lock:
        if state["proc"] is not None:
            return False, "Ja existe uma gravacao em andamento."

        output = opts.get("output") or "transcricao.md"
        cmd = [
            sys.executable,
            "-u",
            "-m",
            "meeting_transcriber",
            "--output",
            output,
            "--title",
            opts.get("title") or "Transcricao de reuniao",
            "--model",
            opts.get("model") or "small",
            "--device",
            opts.get("device") or "cpu",
            "--language",
            opts.get("language") or "pt",
            "--chunk-seconds",
            str(opts.get("chunk_seconds") or 300),
        ]
        if not opts.get("keep_audio", True):
            cmd.append("--no-keep-audio")

        env = {**__import__("os").environ, "PYTHONPATH": str(SRC), "PYTHONUNBUFFERED": "1"}
        creationflags = 0
        if sys.platform == "win32":
            creationflags = subprocess.CREATE_NEW_PROCESS_GROUP

        try:
            proc = subprocess.Popen(
                cmd,
                cwd=str(ROOT),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=creationflags,
            )
        except FileNotFoundError as exc:
            return False, f"Nao consegui iniciar o processo: {exc}"

        state["proc"] = proc
        state["output"] = output
        state["started_at"] = time.time()
        state["finished_at"] = None
        state["exit_code"] = None
        state["log"].clear()

    _log(f"[painel] iniciado: {' '.join(cmd)}")
    threading.Thread(target=_reader_thread, args=(proc,), daemon=True).start()
    return True, "Gravacao iniciada."


def stop_transcriber() -> tuple[bool, str]:
    with state_lock:
        proc = state["proc"]
    if proc is None:
        return False, "Nenhuma gravacao em andamento."

    _log("[painel] parando... aguarde a finalizacao do bloco atual.")
    try:
        proc.terminate()
    except Exception:
        pass

    def _force_kill_later():
        time.sleep(8)
        if proc.poll() is None:
            proc.kill()

    threading.Thread(target=_force_kill_later, daemon=True).start()
    return True, "Parando a gravacao."


def get_status() -> dict:
    with state_lock:
        running = state["proc"] is not None
        return {
            "running": running,
            "output": state["output"],
            "started_at": state["started_at"],
            "finished_at": state["finished_at"],
            "exit_code": state["exit_code"],
            "log": list(state["log"])[-300:],
        }


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):  # noqa: A002 - silencia log padrao no console
        pass

    def _send_json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        if self.path == "/" or self.path == "/index.html":
            self._serve_file(ROOT / "index.html", "text/html; charset=utf-8")
        elif self.path == "/api/status":
            self._send_json(get_status())
        else:
            self.send_error(404)

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            body = {}

        if self.path == "/api/start":
            ok, msg = start_transcriber(body)
            self._send_json({"ok": ok, "message": msg}, 200 if ok else 409)
        elif self.path == "/api/stop":
            ok, msg = stop_transcriber()
            self._send_json({"ok": ok, "message": msg}, 200 if ok else 409)
        else:
            self.send_error(404)

    def _serve_file(self, path: Path, content_type: str) -> None:
        if not path.exists():
            self.send_error(404)
            return
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def main() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    url = f"http://127.0.0.1:{PORT}"
    print(f"Painel disponivel em {url} (Ctrl+C aqui encerra o servidor, nao a gravacao).")
    threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
