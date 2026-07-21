"""Single-owner SQLite worker used by tracking repositories.

The connection is created, used, committed, and closed on the worker thread.
Callers may invoke the synchronous API from any thread without sharing a raw
``sqlite3.Connection`` or disabling SQLite's thread-affinity checks.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from queue import Queue
import sqlite3
from threading import Event, Lock, Thread
from typing import Any, Callable, Iterable, TypeVar


T = TypeVar("T")


@dataclass
class BufferedCursor:
    """Thread-independent snapshot of a completed SQLite cursor."""

    rows: list[sqlite3.Row]
    lastrowid: int | None
    rowcount: int
    _offset: int = 0

    def fetchone(self) -> sqlite3.Row | None:
        if self._offset >= len(self.rows):
            return None
        row = self.rows[self._offset]
        self._offset += 1
        return row

    def fetchall(self) -> list[sqlite3.Row]:
        rows = self.rows[self._offset:]
        self._offset = len(self.rows)
        return rows


@dataclass
class _Command:
    operation: Callable[[sqlite3.Connection], Any]
    completed: Event
    result: Any = None
    error: BaseException | None = None


class SQLiteWorker:
    """Serialize database operations through a connection-owning thread."""

    def __init__(self, db_path: Path | str, *, name: str) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._commands: Queue[_Command | None] = Queue()
        self._started = Event()
        self._closed = Event()
        self._state_lock = Lock()
        self._accepting_commands = True
        self._startup_error: BaseException | None = None
        self._thread = Thread(target=self._run, name=name, daemon=True)
        self._thread.start()
        self._started.wait()
        if self._startup_error is not None:
            raise RuntimeError(f"Unable to open SQLite database: {self.db_path}") from self._startup_error

    @property
    def thread_ident(self) -> int | None:
        return self._thread.ident

    def call(self, operation: Callable[[sqlite3.Connection], T]) -> T:
        command = _Command(operation=operation, completed=Event())
        with self._state_lock:
            if not self._accepting_commands:
                raise RuntimeError("SQLite worker is closed")
            self._commands.put(command)
        command.completed.wait()
        if command.error is not None:
            raise command.error
        return command.result

    def execute(self, sql: str, parameters: Iterable[Any] = (), *, commit: bool = False) -> BufferedCursor:
        values = tuple(parameters)

        def operation(connection: sqlite3.Connection) -> BufferedCursor:
            cursor = connection.execute(sql, values)
            rows = cursor.fetchall() if cursor.description is not None else []
            result = BufferedCursor(rows, cursor.lastrowid, cursor.rowcount)
            if commit:
                connection.commit()
            return result

        return self.call(operation)

    def executemany(self, sql: str, parameters: Iterable[Iterable[Any]], *, commit: bool = False) -> BufferedCursor:
        values = [tuple(row) for row in parameters]

        def operation(connection: sqlite3.Connection) -> BufferedCursor:
            cursor = connection.executemany(sql, values)
            result = BufferedCursor([], cursor.lastrowid, cursor.rowcount)
            if commit:
                connection.commit()
            return result

        return self.call(operation)

    def close(self) -> None:
        with self._state_lock:
            if self._accepting_commands:
                self._accepting_commands = False
                self._commands.put(None)
        self._thread.join()
        self._closed.set()

    def _run(self) -> None:
        try:
            connection = sqlite3.connect(self.db_path)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA busy_timeout = 5000")
            connection.execute("PRAGMA foreign_keys = ON")
        except BaseException as error:
            self._startup_error = error
            self._started.set()
            self._closed.set()
            return

        self._started.set()
        try:
            while True:
                command = self._commands.get()
                if command is None:
                    break
                try:
                    command.result = command.operation(connection)
                except BaseException as error:
                    connection.rollback()
                    command.error = error
                finally:
                    command.completed.set()
        finally:
            connection.close()


class SQLiteConnectionProxy:
    """Compatibility proxy that never exposes the worker's raw connection."""

    def __init__(self, worker: SQLiteWorker) -> None:
        self._worker = worker

    def execute(self, sql: str, parameters: Iterable[Any] = ()) -> BufferedCursor:
        return self._worker.execute(sql, parameters)

    def commit(self) -> None:
        self._worker.call(lambda connection: connection.commit())
