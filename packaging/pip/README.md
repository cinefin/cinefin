# Cinefin — pip / pipx install (Linux)

Run the Cinefin **server** from a self-contained wheel — no Docker, no source
tree. The wheel bundles the SPA build and collected static; only **ffmpeg** is
an optional system dependency (certification/title cards need it —
`sudo apt install ffmpeg` or your distro's equivalent).

## Install & run

```bash
pipx install ./cinefin3-<version>-py3-none-any.whl   # or the URL from a release
cinefin                     # migrate, then serve on 0.0.0.0:8000
```

Open <http://localhost:8000/app/>. Sub-commands:

```bash
cinefin serve      # migrate + serve (the default)
cinefin migrate    # apply migrations and exit
```

Config via env vars: `CINEFIN_HOST` / `CINEFIN_PORT` (default `0.0.0.0:8000`),
`CINEFIN_USERDATA_DIR` (default `~/.local/share/cinefin` — holds the SQLite db,
media, secret key, logs). Keep it to a **single process**: the schedule runner
and playout state are per-process.

To run it on boot, wrap `cinefin` in a systemd **user** service of your own
(`~/.config/systemd/user/`) — nothing is shipped.

## Building the wheel

```bash
packaging/pip/build-wheel.sh     # -> backend/dist/cinefin3-<version>-py3-none-any.whl
```

It builds the SPA, copies it into the package (`cinefin/spa`), runs
`collectstatic`, then `poetry build --format wheel`. CI (`release.yml`) builds
it and attaches the wheel to the edge pre-release and tagged releases.
