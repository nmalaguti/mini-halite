import asyncio
import json
import queue
import socket
import threading
import time
from contextlib import contextmanager

import numpy as np

import structlog

import docker
from docker.errors import ImageNotFound
from docker.types import DeviceRequest
from docker.utils import kwargs_from_env
from docker.utils.socket import frames_iter
from numba import njit

from halite.util import background_thread

log = structlog.get_logger()


class RaisingQueue:
    class _RaiseSentinel:
        def __init__(self, exc_type, exc_value, exc_tb, metadata=None):
            self.exc_type = exc_type
            self.exc_value = exc_value
            self.exc_tb = exc_tb
            self.metadata = metadata or {}

        def raise_exc(self):
            raise self.exc_value.with_traceback(self.exc_tb)

        def describe(self):
            return {
                "type": self.exc_type.__name__,
                "message": str(self.exc_value),
                "metadata": self.metadata,
            }

    class _ShutdownSentinel:
        pass

    def __init__(self, *args, **kwargs):
        self._queue = queue.Queue(*args, **kwargs)

    def raise_(
        self, exc: BaseException, metadata: dict = None, timeout: float = 5.0
    ) -> None:
        """Queue an exception to be raised on the next get()."""
        exc_type, exc_value, exc_tb = type(exc), exc, exc.__traceback__
        self.put(
            self._RaiseSentinel(exc_type, exc_value, exc_tb, metadata=metadata),
            timeout=timeout,
        )

    def put(self, item, timeout: float = None) -> None:
        self._queue.put(item, timeout=timeout)

    def shutdown(self, timeout: float = 5.0):
        self.put(self._ShutdownSentinel(), timeout=timeout)

    def get(self, block=True, timeout=None):
        item = self._queue.get(block=block, timeout=timeout)
        if isinstance(item, self._RaiseSentinel):
            item.raise_exc()
        elif isinstance(item, self._ShutdownSentinel):
            raise ShutdownReceived()
        return item

    @contextmanager
    def capture_exceptions(self, **metadata):
        """Context manager that queues exceptions and re-raises them locally."""
        try:
            yield
        except BaseException as e:
            combined_metadata = {
                "thread": threading.current_thread().name,
                **metadata,
            }
            self.raise_(e, metadata=combined_metadata)
            raise  # re-raise locally


class ShutdownReceived(Exception):
    """
    Raised when the other end of the queue asks for shutdown.
    """


@njit
def encode_halite_rle(map_arr: np.ndarray) -> np.ndarray:
    """
    Encode a (HEIGHT, WIDTH, 2) map into Halite run-length format:
      1) RLE of owner values (count, owner)… until HEIGHT*WIDTH tiles covered
      2) Flat list of strength values, row-major.
    Returns:
      A single string of space-separated integers.
    """
    H, W = map_arr.shape[:2]
    size = H * W

    owners = map_arr[:, :, 0].ravel()
    strengths = map_arr[:, :, 1].ravel()

    # Worst-case: every tile is a different owner → 2 entries per tile
    rle_buffer = np.empty(2 * size + size, dtype=np.int16)
    rle_idx = 0

    # Run-length encode owners
    curr = owners[0]
    count = 1
    for i in range(1, size):
        o = owners[i]
        if o == curr:
            count += 1
        else:
            rle_buffer[rle_idx] = count
            rle_buffer[rle_idx + 1] = curr
            rle_idx += 2
            curr = o
            count = 1
    # Final run
    rle_buffer[rle_idx] = count
    rle_buffer[rle_idx + 1] = curr
    rle_idx += 2

    # Append strengths
    rle_buffer[rle_idx : rle_idx + size] = strengths
    rle_idx += size

    return rle_buffer[:rle_idx]


class DockerSession:
    """
    Context manager for “interactive” Docker container I/O.
    Usage:
        with DockerSession(image='ubuntu:latest') as session:
            session.write_line('echo hello')
            print(session.read_line(timeout=2.0))  # => 'hello\n'
    """

    def __init__(self, image: str, gpu: bool = False):
        self.image = image
        self.gpu = gpu
        self._client = docker.APIClient(**kwargs_from_env())  # low-level client
        self._stdout_q = RaisingQueue()  # holds completed lines
        self.stderr = bytearray()  # raw stderr bytes
        self._stop_event = threading.Event()
        self._start_event = threading.Event()
        self._read_thread = None
        self._container = None
        self._log = log.bind(image=self.image)

        self._ensure_image()

    def _ensure_image(self):
        try:
            self._client.inspect_image(self.image)
        except ImageNotFound:
            self._log.info(f"Docker image not found. Pulling image.")
            progress = {}
            for item in self._client.pull(self.image, stream=True):
                match json.loads(item.decode("utf-8")):
                    case {
                        "status": status,
                        "progressDetail": {"total": total, "current": current},
                        "id": layer_id,
                    }:
                        key = (layer_id, status)
                        progress[key] = (current, total)

    def _wait_for_pid(self, timeout=5.0):
        if self._start_event.is_set():
            return

        self._log.debug(
            "Waiting for PID of Docker container to start...",
        )
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                top = self._client.top(self.container_id)
                if top.get("Processes"):
                    self._log.debug(
                        "PID of Docker container started successfully.",
                        top=top,
                    )
                    self._start_event.set()
                    return
            except Exception:
                self._log.error(
                    "PID of Docker container failed to start.",
                    exc_info=True,
                )
            time.sleep(0.01)
        raise TimeoutError("Container process never started.")

    def __enter__(self):
        # 1) create & start the container (no TTY => no echo)
        if self.gpu:
            self._container = self._client.create_container(
                image=self.image,
                stdin_open=True,
                tty=False,
                runtime="nvidia",
                host_config=self._client.create_host_config(
                    device_requests=[DeviceRequest(count=-1, capabilities=[["gpu"]])]
                ),
            )
        else:
            self._container = self._client.create_container(
                image=self.image,
                stdin_open=True,
                tty=False,
            )

        self.container_id = self._container["Id"]
        self._log = self._log.bind(container=self.container_id)

        # 2) attach a raw socket
        sockobj = self._client.attach_socket(
            container=self.container_id,
            params={"stdin": 1, "stdout": 1, "stderr": 1, "stream": 1},
        )
        self._client.start(self.container_id)

        # grab the real socket and make sure it's blocking
        self._sock: socket.socket = sockobj._sock
        self._sock.setblocking(True)

        # 3) launch reader thread
        self._reader_loop()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()

    @background_thread
    def _reader_loop(self):
        with self._stdout_q.capture_exceptions():
            self._wait_for_pid(timeout=3.0)

            buf = bytearray()
            for stream_id, chunk in frames_iter(self._sock, tty=False):
                if self._stop_event.is_set():
                    self._log.debug(
                        "Stop event is set",
                    )
                    break
                if stream_id == 1:  # stdout
                    buf.extend(chunk)
                    # split out any full lines
                    while b"\n" in buf:
                        line, _, rest = buf.partition(b"\n")
                        self._stdout_q.put(line.decode("utf-8", errors="ignore") + "\n")
                        buf = bytearray(rest)
                else:  # stderr
                    self._log.error(
                        "Container stderr",
                        chunk=chunk.decode(),
                    )
                    self.stderr.extend(chunk)

    def write_line(self, line: str):
        """Send a line (with trailing \\n) to the container’s stdin."""
        self._start_event.wait()

        if not line.endswith("\n"):
            line += "\n"

        # Docker’s multiplexed stdin is raw: just send bytes
        self._sock.sendall(line.encode("utf-8"))

    def read_line(self, timeout: float = None) -> str:
        """
        Block up to `timeout` seconds waiting for the next stdout line.
        Raises queue.Empty on timeout.
        """
        return self._stdout_q.get(timeout=timeout)

    def close(self):
        # signal reader thread to stop
        self._stop_event.set()

        # close write end so the shell will exit
        try:
            self._sock.shutdown(socket.SHUT_WR)
        except OSError:
            pass

        # wait for reader to finish up
        if self._read_thread is not None:
            self._read_thread.join(timeout=1.0)

        # stop & remove the container
        self._client.stop(self.container_id)
        self._client.remove_container(self.container_id, force=True)

        # close the socket
        try:
            self._sock.close()
        except OSError:
            pass


class DockerAdapter:
    def __init__(self, image: str, name: str | None = None, gpu: bool = False):
        self.bot_id = 0
        self.name = name
        self._log = log
        self.image = image
        self.gpu = gpu
        self._log = self._log.bind(image=self.image, name=self.name)

    def send_init_sync(
        self,
        bot_id: int,
        dims: tuple[int, int],
        production: np.ndarray,
        first_frame: np.ndarray,
        timeout: float = 30.0,
    ) -> str:
        self.bot_id = bot_id
        self._log = self._log.bind(bot_id=bot_id)
        self._log.debug("Send init")

        try:
            self.session.write_line(f"{bot_id}")
            self.session.write_line(" ".join(map(str, dims)))
            self.session.write_line(" ".join(map(str, production.ravel())))
            self.session.write_line(" ".join(map(str, encode_halite_rle(first_frame))))

            self._log.debug("Waiting for name")
            bot_name = self.session.read_line(timeout=timeout).rstrip()

            if self.name is not None:
                bot_name = self.name

            self._log.debug("bot ready", name=bot_name)

            return bot_name
        except queue.Empty:
            raise TimeoutError(
                f"SessionAdapter for '{self.bot_id}' timed out during init"
            )

    async def send_init(
        self,
        bot_id: int,
        dims: tuple[int, int],
        production: np.ndarray,
        first_frame: np.ndarray,
        timeout: float = 30.0,
    ) -> str:
        return await asyncio.to_thread(
            self.send_init_sync, bot_id, dims, production, first_frame, timeout
        )

    def send_frame_sync(self, frame: np.ndarray, timeout: float = 5.0) -> np.ndarray:
        self.session.write_line(" ".join(map(str, encode_halite_rle(frame))))
        try:
            moves_str = self.session.read_line(timeout=timeout).rstrip()
        except queue.Empty:
            raise TimeoutError(
                f"SessionAdapter for '{self.bot_id}' timed out during frame"
            )

        moves = np.zeros_like(frame[..., 0], dtype=np.int16)
        if not moves_str:
            return moves

        data = np.fromstring(moves_str, sep=" ", dtype=np.int16)

        if data.size % 3 != 0:
            raise ValueError(f"Invalid move string from bot: {moves_str!r}")

        data = data.reshape(-1, 3)
        x, y, d = data[:, 0], data[:, 1], data[:, 2]

        H, W = moves.shape
        in_bounds = (x >= 0) & (x < W) & (y >= 0) & (y < H)

        x_in, y_in, d_in = x[in_bounds], y[in_bounds], d[in_bounds]
        owned = frame[y_in, x_in, 0] == self.bot_id

        valid_x, valid_y, valid_d = x_in[owned], y_in[owned], d_in[owned]
        moves[valid_y, valid_x] = valid_d

        return moves

    def init_session(self) -> DockerSession:
        return DockerSession(self.image, gpu=self.gpu).__enter__()

    async def send_frame(self, frame: np.ndarray, timeout: float = 5.0) -> np.ndarray:
        return await asyncio.to_thread(self.send_frame_sync, frame, timeout)

    async def __aenter__(self):
        self.session = await asyncio.to_thread(self.init_session)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        self.session.close()
