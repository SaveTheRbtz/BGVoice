# Local generated data

BGVoice writes its generated pipeline database here as the `bgvoice.lancedb` directory.
The local IESDP reference archive may also be unpacked as `iesdp-gh-pages`.

Everything except this README is ignored by Git because these are reproducible, machine-local
artifacts that can be large or contain copyrighted game text. Do not commit them.

The web UI only reads committed LanceDB table versions, so it can browse while extraction writes
new snapshots. Treat the database as one directory; stop writers before copying or moving it.
