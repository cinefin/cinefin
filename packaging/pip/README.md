# Cinefin — pip / pipx install (Linux)

Run the Cinefin **server** from a self-contained wheel — no Docker, no source
tree. The wheel bundles the SPA build and collected static; only **ffmpeg** is
an optional system dependency (certification/title cards need it —
`sudo apt install ffmpeg` or your distro's equivalent).

## Install & run

```bash
pipx install ./cinefin-<version>-py3-none-any.whl   # or the URL from a release
cinefin serve               # migrate, then serve on 0.0.0.0:8000
```

The command and its flags are described in the top-level README ("Linux: pip /
pipx") and in `cinefin --help`. Data goes to `~/.local/share/cinefin` unless
`--data-dir` or `CINEFIN_USERDATA_DIR` says otherwise. Keep it to a **single
process**: the schedule runner and playout state are per-process.

To run it on boot, `packaging/systemd/cinefin.service.example` is a system unit
that runs `cinefin serve --data-dir /var/lib/cinefin`.

## Building the wheel

```bash
packaging/pip/build-wheel.sh     # -> backend/dist/cinefin-<version>-py3-none-any.whl
```

It builds the SPA, copies it into the package (`cinefin/spa`), runs
`collectstatic`, then `poetry build --format wheel`. CI (`release.yml`) builds
it and attaches the wheel to the edge pre-release and tagged releases.
