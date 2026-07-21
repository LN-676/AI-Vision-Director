# Phase 7: SQLite Thread Ownership

`VehicleIdentityStore` and `FeatureRepository` no longer share a raw SQLite
connection between Tkinter, tracking, and helper threads. Each repository owns
an `SQLiteWorker` with these rules:

- the worker creates and closes its connection on the database thread;
- callers submit synchronous commands through a queue;
- query rows and cursor metadata are copied before crossing thread boundaries;
- commits and rollbacks occur on the connection-owning thread;
- SQLite's default thread-affinity protection remains enabled;
- `busy_timeout` allows the identity and feature workers to coordinate safely
  while using the same database file.

`VehicleIdentityStore` retains batched frame updates. Its in-memory pending
buffer is protected separately, then flushed with one queued `executemany`
transaction. `SQLiteConnectionProxy` preserves the limited historical
`connection.execute(...).fetch*()` surface without exposing the raw connection.
