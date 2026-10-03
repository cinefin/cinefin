# System Ident source

`ident.html` is the source of the bundled System Ident,
`backend/cinefin/assets/system/ident.mp4`. `render.mjs` turns it into the video.

## The clip

- 1920x1080, 30 fps, 34 s, H.264 High 4.1 (8-bit yuv420p, BT.709), no
  audio, about 2.5 Mbit/s.
- 0 to 4 s: the intro. The mark's three cells strike in, the frame and perfs
  fade up, the wordmark slides in and three soft colour blooms unfold into an
  orbit around the lockup. Everything is at rest by 4.0 s.
- 4 to 34 s: a seamless loop. The orbit turns 360 degrees in 30 s and the
  blooms breathe with periods of 10, 15 and 30 s, so the frame at 34 s equals
  the frame at 4 s. A player holds the ident by looping this range (mpv
  `ab-loop-a=4`, `ab-loop-b=34`); the backend has it as `SYSTEM_IDENT_LOOP`
  in `backend/cinefin/api/utils/assets.py`.
- Keyframes are forced at 0 s and 4 s so the loop start is a clean seek point.

## Details that matter

- Sharpness: the mark is 96x128 css px, 4 device px per logo unit, and the
  lockup is placed on a css x that is a multiple of 4 px, so every edge of
  the frame, perfs and cells lands on an even pixel of the 1080p frame. The
  rest of the lockup is the mock's, scaled by 16/15 to match.
- Nothing invisible stays rendered: the intro's CSS animations only exist
  while the stage has the `intro` class (t < 4 s), and the blurred halo and
  cell-glow copies are only displayed while they animate. A blurred copy
  left in the tree at opacity 0 made Chromium paint a dark block over the
  mark.
- The orbit light is not CSS gradients. The page draws it into a canvas at
  device resolution in float and quantises it with a fixed per-pixel dither
  threshold, so the dark gradients do not band. The canvas is a software
  canvas (`willReadFrequently`): an accelerated one put the lockup on a
  composited layer that Chromium drew 1.5 px off, which blurred the mark.
- Encoding keeps that dither: zscale converts RGB to YUV with error
  diffusion, and x264 runs at CRF 14 with `-tune film`, `aq-mode=3` and small
  deadzones.

## Rendering

Needs ffmpeg with zscale (libzimg) on `PATH` and Playwright's Chromium (`npx playwright install
chromium`, or set `PLAYWRIGHT_CHROMIUM_PATH` to a system Chromium).

```bash
cd frontend
npm run render:ident                        # writes backend/cinefin/assets/system/ident.mp4
npm run render:ident -- --out /tmp/ident.mp4  # somewhere else
```

The script loads the page headless at 1280x720 with a device scale factor of
1.5 (so the 1280x720 design renders at 1920x1080), pauses every animation,
seeks the page to each frame time with `window.identSeek(t)` and pipes PNG
screenshots to ffmpeg. It takes about five minutes. At the end it renders one
extra frame at 34 s and compares it with the 4 s frame; it prints the result
and exits non-zero if they differ.

Opening `ident.html` in a browser plays it live, looping 4 to 34 s.

Fonts are the SPA's bundled faces from `frontend/src/lib/assets/fonts/`:
Tilt Warp 400 for the wordmark and Archivo 500 for "HOME THEATER". Nothing is
fetched from the network.
