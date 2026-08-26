# Local generated data

BGVoice writes its generated pipeline database here as `bgvoice.sqlite3`. SQLite may also create
`-wal` and `-shm` sidecars while the database is open.

These files are ignored by Git because they are reproducible, machine-local extracts that can be
large and contain copyrighted game text. Do not commit them.

The web UI opens the database read-only. WAL mode lets it browse while extraction writes, but an
active database must stay with its sidecars; stop the processes before copying or moving it.
