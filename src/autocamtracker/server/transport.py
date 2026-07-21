"""WebSocket byte/text transport with no CV-domain dependencies or state."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import ipaddress
import re
import shutil
import socket
import subprocess
import threading
from typing import Any, Callable


@dataclass(frozen=True)
class TrackingServerConfig:
    host: str = "0.0.0.0"
    port: int = 8765
    path: str = "/ws/tracking"
    publish_hz: float = 20.0


class WebSocketTransport:
    """Own sockets and connection lifecycle; exchange only raw bytes/text."""

    def __init__(
        self,
        config: TrackingServerConfig,
        *,
        on_binary: Callable[[bytes], None],
        on_text: Callable[[str], None],
        initial_messages: Callable[[], list[str]],
        on_connected: Callable[[int], None] | None = None,
        on_disconnected: Callable[[int], None] | None = None,
        on_status: Callable[[str], None] | None = None,
        on_event: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> None:
        self.config = config
        self.on_binary = on_binary
        self.on_text = on_text
        self.initial_messages = initial_messages
        self.on_connected = on_connected
        self.on_disconnected = on_disconnected
        self.on_status = on_status
        self.on_event = on_event
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stop_event: asyncio.Event | None = None
        self._clients: set[Any] = set()
        self._running = threading.Event()
        self._bonjour_process: subprocess.Popen[str] | None = None

    @property
    def is_running(self) -> bool:
        return self._running.is_set()

    @property
    def client_count(self) -> int:
        return len(self._clients)

    @property
    def local_urls(self) -> list[str]:
        addresses = {address for _, address in self._active_interface_addresses()}
        hostname = socket.gethostname()
        local_name = hostname if hostname.endswith(".local") else f"{hostname}.local"
        try:
            addresses.update(socket.gethostbyname_ex(hostname)[2])
        except OSError:
            pass
        usable = [address for address in addresses if ":" not in address and not address.startswith("127.")]
        link_local = sorted(address for address in usable if ipaddress.ip_address(address).is_link_local)
        private = sorted(address for address in usable if ipaddress.ip_address(address).is_private and address not in link_local)
        other = sorted(address for address in usable if address not in link_local and address not in private)
        urls = [f"ws://{local_name}:{self.config.port}{self.config.path}"]
        urls.extend(
            f"ws://{address}:{self.config.port}{self.config.path}"
            for address in (*private, *link_local, *other)
        )
        return urls

    @property
    def preferred_url(self) -> str:
        return self.local_urls[0]

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._thread_main, name="tracking-websocket", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._loop is not None and self._stop_event is not None and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._stop_event.set)
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        self._thread = None
        self._running.clear()

    def publish_text(self, message: str) -> None:
        if self._loop is None or not self._loop.is_running():
            return
        asyncio.run_coroutine_threadsafe(self._broadcast(message), self._loop)

    def _thread_main(self) -> None:
        try:
            asyncio.run(self._serve())
        except Exception as error:  # pragma: no cover - surfaced through status callback
            self._notify(f"iPhone server failed: {error}")
        finally:
            self._stop_bonjour_registration()
            self._running.clear()
            self._loop = None
            self._stop_event = None

    async def _serve(self) -> None:
        try:
            from websockets.asyncio.server import serve
        except ImportError as error:
            raise RuntimeError("Install the 'websockets' dependency first") from error
        self._loop = asyncio.get_running_loop()
        self._stop_event = asyncio.Event()
        async with serve(self._handle_client, self.config.host, self.config.port):
            self._start_bonjour_registration()
            self._running.set()
            self._notify(f"Waiting for iPhone · {self.preferred_url}")
            try:
                await self._stop_event.wait()
            finally:
                self._stop_bonjour_registration()
        self._clients.clear()

    def _start_bonjour_registration(self) -> None:
        """Advertise the tracking endpoint without adding a Python dependency."""

        if self._bonjour_process is not None or self.config.host not in {"0.0.0.0", "::"}:
            return
        executable = shutil.which("dns-sd")
        if executable is None:
            self._notify("Bonjour unavailable; use the displayed WebSocket URL")
            return
        service_name = socket.gethostname().removesuffix(".local")
        try:
            self._bonjour_process = subprocess.Popen(
                [
                    executable,
                    "-R",
                    service_name,
                    "_autocamtracker._tcp",
                    "local.",
                    str(self.config.port),
                    f"path={self.config.path}",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                text=True,
            )
        except OSError as error:
            self._notify(f"Bonjour registration failed: {error}")

    def _stop_bonjour_registration(self) -> None:
        process = self._bonjour_process
        self._bonjour_process = None
        if process is None or process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=1.0)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=1.0)

    async def _handle_client(self, websocket: Any) -> None:
        from websockets.exceptions import ConnectionClosed

        request_path = getattr(getattr(websocket, "request", None), "path", "")
        if request_path.split("?", 1)[0] != self.config.path:
            await websocket.close(code=1008, reason="Unsupported path")
            return
        self._clients.add(websocket)
        self._emit("ws_client_connected", path=request_path, client_count=len(self._clients))
        if self.on_connected is not None:
            self.on_connected(len(self._clients))
        for message in self.initial_messages():
            await websocket.send(message)
        try:
            async for message in websocket:
                if isinstance(message, bytes):
                    self.on_binary(message)
                elif isinstance(message, str):
                    self.on_text(message)
        except ConnectionClosed:
            pass
        finally:
            self._clients.discard(websocket)
            count = len(self._clients)
            if self.on_disconnected is not None:
                self.on_disconnected(count)
            self._emit("ws_client_disconnected", client_count=count)

    async def _broadcast(self, message: str) -> None:
        if not self._clients:
            return
        clients = list(self._clients)
        results = await asyncio.gather(*(client.send(message) for client in clients), return_exceptions=True)
        for client, result in zip(clients, results):
            if isinstance(result, Exception):
                self._clients.discard(client)

    @staticmethod
    def _active_interface_addresses() -> list[tuple[str, str]]:
        try:
            result = subprocess.run(["ifconfig"], check=False, capture_output=True, text=True, timeout=2.0)
        except (OSError, subprocess.SubprocessError):
            return []
        interfaces: dict[str, dict[str, Any]] = {}
        current: str | None = None
        for line in result.stdout.splitlines():
            match = re.match(r"^([a-zA-Z0-9]+):", line)
            if match:
                current = match.group(1)
                interfaces[current] = {"addresses": [], "active": False}
                continue
            if current is None:
                continue
            address_match = re.match(r"\s+inet (\d+\.\d+\.\d+\.\d+)\b", line)
            if address_match:
                interfaces[current]["addresses"].append(address_match.group(1))
            if line.strip() == "status: active":
                interfaces[current]["active"] = True
        return [
            (name, address)
            for name, state in interfaces.items()
            if state["active"]
            for address in state["addresses"]
            if not address.startswith("127.")
        ]

    def _notify(self, message: str) -> None:
        if self.on_status is not None:
            self.on_status(message)

    def _emit(self, event: str, **fields: Any) -> None:
        if self.on_event is not None:
            self.on_event(event, fields)
