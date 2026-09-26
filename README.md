<p align="center">
  <img src="logo.svg" alt="Cinefin" height="120">
</p>

<h1 align="center">Cinefin</h1>

<p align="center"><em>A theater at home.</em></p>

<p align="center">
  <a href="https://github.com/cinefin/cinefin/actions/workflows/ci.yml"><img src="https://github.com/cinefin/cinefin/actions/workflows/ci.yml/badge.svg" alt="CI"></a> 
  <a href="https://github.com/cinefin/cinefin/releases/latest"><img src="https://img.shields.io/github/v/release/cinefin/cinefin?sort=semver" alt="Latest release"></a>
  <a href="https://github.com/cinefin/cinefin/pkgs/container/cinefin"><img src="https://img.shields.io/badge/ghcr.io-cinefin-2496ED?logo=docker&logoColor=white" alt="Container image"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-AGPL_v3-blue.svg" alt="License: AGPL v3"></a>
</p>

<p align="center">
  <a href="https://docs.cinefin.dev"><b>Documentation</b></a> ·
  <a href="https://github.com/cinefin/cinefin/releases/latest"><b>Download</b></a> ·
  <a href="https://github.com/cinefin/cinefin-playout"><b>Playout agent</b></a>
</p>

---

Turn your living room into a functioning theater. Cinefin uses your Jellyfin
or Plex media library to build and schedule theater programmes by fetching 
trailers, managing custom pre-roll media, and running home automation commands. 
It even prints tickets!

## Features

- **Library sync** from Plex and Jellyfin
- **Programmes** sequence trailers, custom media, ratings cards, commands and the features
- **Smart trailers** match on genre, year and certification of what's showing
- **Playout via MPV** embedded, or connect your own (local or network)
- **Ratings cards** for BBFC or MPAA
- **Home automation** - Home Assistant and generic REST supported
- **Scheduling** - run screenings automatically
- **Kiosk mode** for front of house, **remote control** from your phone
- **Ticket printing** on ESC/POS thermal printers

## Download & run

Pick one of the options below, then open
<http://localhost:8000> and follow the setup wizard. All your data lives under `./userdata`.

### Docker (recommended)

```bash
cd docker
CINEFIN_SERVER_URL='http://localhost:8000' docker compose up -d --build
```

### Linux — pip / pipx

Install `ffmpeg` using your distro's package manager

Grab the latest `cinefin3-*.whl` from the
[**releases page**](https://github.com/cinefin/cinefin/releases/latest):

```bash
pipx install ./cinefin3-<version>-py3-none-any.whl   # paste the release URL
cinefin                                              # migrate, then serve on :8000
```

> [!NOTE]
> Playback needs a player: run the
> [**Playout agent**](https://github.com/cinefin/cinefin-playout) on your cinema
> box, or point Cinefin at your own [MPV](https://mpv.io) instance started with
> `--input-ipc-server`. See the [docs](https://docs.cinefin.dev) for setup.

## License

[AGPL v3](LICENSE). Cinefin is for home use — not commercial cinema installations.
