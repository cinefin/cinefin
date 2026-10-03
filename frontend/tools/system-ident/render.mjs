// Render the System Ident (ident.html) to backend/cinefin/assets/system/ident.mp4.
//
//   cd frontend && npm run render:ident [-- --out /path/to/ident.mp4]
//
// Loads the page in headless Chromium, pauses every animation and seeks the
// page to each frame time (window.identSeek), screenshots 1920x1080 PNGs and
// pipes them to ffmpeg (H.264 High 4.1, yuv420p, no audio, keyframes forced at
// 0 s and at the loop start). It then renders one extra frame at the loop end
// and compares it with the loop-start frame, so a broken loop is caught here.
// Needs ffmpeg (built with libzimg, for zscale) on PATH and Playwright's Chromium (`npx playwright install chromium`).

import { spawn, spawnSync } from 'node:child_process';
import { mkdtempSync, rmSync, writeFileSync, statSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { chromium } from '@playwright/test';

const here = dirname(fileURLToPath(import.meta.url));
const FPS = 30;
const WIDTH = 1280; // stage size; deviceScaleFactor 1.5 renders it at 1920x1080
const HEIGHT = 720;

const args = process.argv.slice(2);
const outIdx = args.indexOf('--out');
const crfIdx = args.indexOf('--crf');
// The dark gradients carry a fine dither (see ident.html). To keep it: the
// RGB to YUV conversion is zscale with error diffusion (swscale would
// requantise without dithering and bring the bands back), and x264 runs at
// CRF 14 with aq-mode 3 (more bits for dark flat areas) and small deadzones
// so it does not smooth the dither away. About 2.5 Mbit/s.
const CRF = crfIdx >= 0 ? Number(args[crfIdx + 1]) : 14;
const out = resolve(
	outIdx >= 0 ? args[outIdx + 1] : join(here, '../../../backend/cinefin/assets/system/ident.mp4')
);

const browser = await chromium.launch({
	...(process.env.PLAYWRIGHT_CHROMIUM_PATH
		? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_PATH }
		: {})
});
const page = await browser.newPage({
	viewport: { width: WIDTH, height: HEIGHT },
	deviceScaleFactor: 1.5
});
await page.goto(pathToFileURL(join(here, 'ident.html')).href + '?render');
await page.evaluate(() => window.identReady);
const fontsOk = await page.evaluate(
	() =>
		document.fonts.check("46.9333px 'Tilt Warp'") && document.fonts.check("500 13.3333px 'Archivo'")
);
if (!fontsOk) throw new Error('bundled fonts did not load');
const [loopA, loopB] = await page.evaluate(() => window.identLoop);

async function frameAt(t) {
	await page.evaluate((t) => window.identSeek(t), t);
	return page.screenshot({ type: 'png', animations: 'allow', caret: 'initial' });
}

const total = Math.round(loopB * FPS); // frames 0 .. total-1 cover 0 .. loopB
const ffmpeg = spawn(
	'ffmpeg',
	[
		'-y',
		'-hide_banner',
		'-loglevel',
		'error',
		'-f',
		'image2pipe',
		'-framerate',
		String(FPS),
		'-c:v',
		'png',
		'-i',
		'-',
		'-an',
		'-vf',
		'zscale=m=709:r=limited:d=error_diffusion,format=yuv420p',
		'-c:v',
		'libx264',
		'-profile:v',
		'high',
		'-level:v',
		'4.1',
		'-tune',
		'film',
		'-x264-params',
		'aq-mode=3:deadzone-inter=6:deadzone-intra=6',
		'-preset',
		'slow',
		'-crf',
		String(CRF),
		'-g',
		String(FPS * 2),
		'-force_key_frames',
		`0,${loopA}`,
		'-colorspace',
		'bt709',
		'-color_primaries',
		'bt709',
		'-color_trc',
		'bt709',
		'-color_range',
		'tv',
		'-movflags',
		'+faststart',
		out
	],
	{ stdio: ['pipe', 'inherit', 'inherit'] }
);
const done = new Promise((ok, fail) =>
	ffmpeg.on('close', (code) => (code === 0 ? ok() : fail(new Error(`ffmpeg exited ${code}`))))
);

let seamA;
for (let i = 0; i < total; i++) {
	const png = await frameAt(i / FPS);
	if (i === Math.round(loopA * FPS)) seamA = png;
	if (!ffmpeg.stdin.write(png)) await new Promise((r) => ffmpeg.stdin.once('drain', r));
	if (i % FPS === 0) process.stdout.write(`\r${(i / FPS).toFixed(0)} s / ${loopB} s`);
}
ffmpeg.stdin.end();
await done;
process.stdout.write('\n');

// Seam check: the frame at loopB must equal the frame at loopA.
const seamB = await frameAt(loopB);
await browser.close();
const tmp = mkdtempSync(join(tmpdir(), 'ident-seam-'));
try {
	writeFileSync(join(tmp, 'a.png'), seamA);
	writeFileSync(join(tmp, 'b.png'), seamB);
	if (seamA.equals(seamB)) {
		console.log(`seam: frame at ${loopB} s is byte-identical to the frame at ${loopA} s`);
	} else {
		const r = spawnSync(
			'ffmpeg',
			[
				'-hide_banner',
				'-i',
				join(tmp, 'a.png'),
				'-i',
				join(tmp, 'b.png'),
				'-lavfi',
				'psnr',
				'-f',
				'null',
				'-'
			],
			{ encoding: 'utf8' }
		);
		const psnr = (r.stderr.match(/PSNR .*/) || ['psnr unavailable'])[0];
		console.log(`seam: frames at ${loopA} s and ${loopB} s differ: ${psnr}`);
		process.exitCode = 1;
	}
} finally {
	rmSync(tmp, { recursive: true, force: true });
}

console.log(
	`wrote ${out} (${(statSync(out).size / 1e6).toFixed(2)} MB, ${total} frames at ${FPS} fps)`
);
