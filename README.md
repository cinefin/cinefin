<p align="center">
  <img src="logo.png" alt="" height="110">
</p>

<h1 align="center">Cinefin</h1>

<p align="center"><em>A theater at home.</em></p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-AGPL_v3-blue.svg" alt="License: AGPL v3"></a>
</p>

Turn your digital film collection into functioning theater! Cinefin manages
and plays trailers, ratings cards, custom pre-roll and all sorts of user
media. Build out programmes, schedule screenings, and run a theater at home.

Free and open-source software. Cinefin is designed for home use, not commercial installations.

## Current features

- **Sync your movie libraries** from Plex and Jellyfin
- **Builds programmes**: trailers, pre-roll, home automation, movies
- **Playout via MPV**: the player comes embedded, or connect your own
  instance (local or network)
- **Configurable trailer matching** on the genre, year and certification of
  upcoming movies
- Can be used with **BBFC or MPAA ratings cards**
- **Design and load title cards** for screenings
- **Home Assistant and generic REST integration** for home automation
- **Runs screenings on a schedule**
- **Kiosk mode** for front of house
- **Remote control** from your phone
- **Prints tickets** on a thermal printer(!)

## Quick start (Docker)

**Full documentation and a user guide are currently being worked on and will be released shortly**

Docker is the easiest way to run the Cinefin server. From the repo root:

```bash
cd docker
CINEFIN_SERVER_URL='http://localhost:8000' docker compose up -d --build
```

Then open <http://localhost:8000> and follow the setup wizard. Cinefin creates
and migrates its database on first start; all your data lives in `./userdata`.

Change `CINEFIN_SERVER_URL` if you are using a different domain/port.

You will need to either run the the [Playout agent](https://github.com/cinefin/cinefin-playout) or an instance of [MPV](https://mpv.io) with a JSON-IPC socket file configured using ` --input-ipc-server`.


