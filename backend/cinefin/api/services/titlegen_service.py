"""Programme title cards: Pillow composition + ffmpeg video generation."""

import logging
import os
import subprocess
from io import BytesIO
from pathlib import Path

from django.conf import settings
from PIL import Image, ImageDraw, ImageFont

from cinefin.api.services import poster_service
from cinefin.api.utils.media_paths import to_usermedia_relative, usermedia_abs_path

logger = logging.getLogger(__name__)

LANCZOS = Image.Resampling.LANCZOS

# Fonts shipped with the app (cinefin/static/fonts/, all SIL OFL). Bundled so the rendered card and the editor's
# browser preview (@font-face on the same files) agree — system fonts vary per box and PIL quietly falls back to
# DejaVu when a name doesn't resolve.
BUNDLED_FONTS = {
    "Bebas Neue": "BebasNeue.ttf",
    "Courier Prime": "CourierPrime.ttf",
    "Inter": "Inter.ttf",
    "Oswald": "Oswald.ttf",
    "Playfair Display": "PlayfairDisplay.ttf",
}

# Unbundled sans names would fall back to DejaVu here (and a system font in the browser), so map them to a
# bundled face to keep the card and the editor's WYSIWYG preview identical.
DEFAULT_FONT = "Inter"
BUNDLED_ALIASES = {"Arial": "Inter", "Helvetica": "Inter", "sans-serif": "Inter"}

# System fonts the discovery endpoint probes for; only ones PIL can load are offered.
SYSTEM_FONT_CANDIDATES = [
    "Arial",
    "Arial Black",
    "Helvetica",
    "Times New Roman",
    "Georgia",
    "Courier New",
    "Verdana",
    "Impact",
]


def bundled_fonts_dir() -> Path:
    return Path(settings.BASE_DIR) / "cinefin" / "static" / "fonts"


def title_length(programme) -> int | None:
    """How long the programme's title card runs, in seconds: the background video's length,
    else the template default. None without a title template."""
    if not programme.title_template_id:
        return None
    if programme.title_background_type == "video" and programme.title_background_file:
        from cinefin.api.ninja_views.media.utils import get_media_duration

        video_duration = get_media_duration(usermedia_abs_path(programme.title_background_file))
        if video_duration:
            return int(video_duration)
    return programme.title_template.default_duration


class TitleGenService:
    def __init__(self, programme):
        self.programme = programme
        self.template = programme.title_template
        self.output_dir = Path(settings.MEDIA_ROOT) / "programme_titles"
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def generate_title(self) -> dict[str, any]:
        if not self.template:
            return {"success": False, "error": "No title template configured for this programme"}

        try:
            config = self.template.template_config
            if not config:
                return {"success": False, "error": "Template has no configuration"}

            canvas = config.get("canvas", {"width": 1920, "height": 1080})
            width = canvas.get("width", 1920)
            height = canvas.get("height", 1080)
            duration = title_length(self.programme)

            temp_image_path = self.output_dir / f"temp_{self.programme.id}.png"
            self._render_frame(width, height, config).save(temp_image_path, "PNG")
            output_file = self._generate_video(temp_image_path, width, height, duration)
            temp_image_path.unlink(missing_ok=True)

            # Store MEDIA_ROOT-relative so the card survives a moved media volume.
            self.programme.title_file = to_usermedia_relative(str(output_file))
            self.programme.save(update_fields=["title_file"])

            return {"success": True, "file_path": str(output_file), "duration": duration}

        except Exception as e:
            logger.exception(f"Failed to generate title for programme {self.programme.id}")
            return {"success": False, "error": str(e)}

    @staticmethod
    def _placeholder_movies() -> list:
        """Design-view stand-ins matching the editor's canvas placeholders."""
        from types import SimpleNamespace

        movie = {"title": "Movie Title", "director": "Director Name", "year": 2024, "certification": "PG-13"}
        return [SimpleNamespace(**movie, runtime=120, poster_key="") for _ in range(4)]

    @classmethod
    def render_config_frame(cls, config: dict, programme=None) -> Image.Image:
        """Ground-truth preview using the generator's exact render code."""
        inst = cls.__new__(cls)  # no __init__: previews need no template/output dir
        inst.programme = programme
        inst._preview_mode = True
        canvas = config.get("canvas", {"width": 1920, "height": 1080})
        frame = inst._render_frame(canvas.get("width", 1920), canvas.get("height", 1080), config)
        # The real card composites over a background video/black; previews use near-black so transparency reads.
        background = Image.new("RGB", frame.size, (16, 16, 16))
        background.paste(frame, (0, 0), frame)
        return background

    def _render_frame(self, width: int, height: int, config: dict) -> Image.Image:
        image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        movies = self.programme.get_feature_movies() if self.programme else self._placeholder_movies()
        for element in config.get("elements", []):
            match element.get("type"):
                case "poster":
                    self._render_poster(image, element, movies)
                case "text":
                    self._render_text(draw, element, movies)
                case "image":
                    self._render_image(image, element)
                case "rectangle":
                    self._render_rectangle(draw, element)
        return image

    @staticmethod
    def _paste(image: Image.Image, layer: Image.Image, element: dict) -> None:
        """Paste `layer` at the element's x/y, faded by its opacity."""
        layer = layer.convert("RGBA")
        opacity = element.get("opacity", 1.0)
        if opacity < 1.0:
            layer.putalpha(layer.split()[-1].point(lambda p: int(p * opacity)))
        image.paste(layer, (int(element.get("x", 0)), int(element.get("y", 0))), layer)

    def _render_poster(self, image: Image.Image, element: dict, movies: list) -> None:
        feature_index = element.get("feature_index", 0)
        movie = movies[feature_index] if feature_index < len(movies) else None
        # A live fetch from the media server: one that is asleep means no poster on the card, not a failed render.
        content = poster_service.fetch_poster(movie) if movie is not None and movie.poster_key else None
        if content is None:
            if getattr(self, "_preview_mode", False):
                self._render_poster_placeholder(image, element)
            else:
                logger.warning(f"No usable poster for feature {feature_index + 1}")
            return

        try:
            size = (int(element.get("width", 300)), int(element.get("height", 450)))
            self._paste(image, Image.open(BytesIO(content)).resize(size, LANCZOS), element)
        except Exception as e:
            logger.error(f"Failed to render poster for {movie.title}: {e}")

    @staticmethod
    def _render_poster_placeholder(image: Image.Image, element: dict) -> None:
        """Grey stand-in box where a poster would go (previews only)."""
        x, y = int(element.get("x", 0)), int(element.get("y", 0))
        w, h = int(element.get("width", 300)), int(element.get("height", 450))
        box = Image.new("RGBA", (w, h), (42, 42, 42, 255))
        draw = ImageDraw.Draw(box)
        draw.rectangle((0, 0, w - 1, h - 1), outline=(90, 90, 90, 255), width=3)
        draw.line((0, 0, w - 1, h - 1), fill=(70, 70, 70, 255), width=2)
        draw.line((w - 1, 0, 0, h - 1), fill=(70, 70, 70, 255), width=2)
        image.paste(box, (x, y), box)

    @staticmethod
    def _parse_hex_rgb(color_hex: str, default: tuple[int, int, int] = (255, 255, 255)) -> tuple[int, int, int]:
        """Hex colour -> (r, g, b), tolerant of #RGB and junk: a bad saved colour must not 500 the previews."""
        h = (color_hex or "").lstrip("#").strip()
        if len(h) == 3:
            h = "".join(c * 2 for c in h)  # #abc -> #aabbcc
        try:
            return tuple(int(h[i : i + 2], 16) for i in (0, 2, 4))
        except (ValueError, IndexError):
            return default

    def _render_text(self, draw: ImageDraw.Draw, element: dict, movies: list) -> None:
        text = self._get_text_value(element.get("field"), element.get("feature_index", 0), movies)
        if not text:
            return

        font_size = int(element.get("size", 48))
        font = self._load_font(element.get("font") or DEFAULT_FONT, font_size)
        x, y = int(element.get("x", 0)), int(element.get("y", 0))
        color = (*self._parse_hex_rgb(element.get("color", "#FFFFFF")), int(255 * element.get("opacity", 1.0)))

        max_width = element.get("max_width")
        if not max_width:
            draw.text((x, y), text, fill=color, font=font)
            return
        # Word-wrap and align within a box of max_width.
        max_width = int(max_width)
        try:
            ascent, descent = font.getmetrics()
            line_height = int((ascent + descent) * 1.1)
        except Exception:
            line_height = int(font_size * 1.2)
        align = element.get("align", "left")
        for i, line in enumerate(self._wrap_text(draw, text, font, max_width)):
            slack = max_width - draw.textlength(line, font=font)
            lx = x + {"center": slack // 2, "right": slack}.get(align, 0)
            draw.text((int(lx), y + i * line_height), line, fill=color, font=font)

    @staticmethod
    def _wrap_text(draw, text, font, max_width):
        """Greedy word-wrap so no line exceeds max_width."""
        words = text.split()
        if not words:
            return [""]
        lines = []
        current = words[0]
        for word in words[1:]:
            candidate = current + " " + word
            if draw.textlength(candidate, font=font) <= max_width:
                current = candidate
            else:
                lines.append(current)
                current = word
        lines.append(current)
        return lines

    def _get_text_value(self, field: str, feature_index: int, movies: list) -> str | None:
        if feature_index >= len(movies):
            return None
        movie = movies[feature_index]
        if field == "programme_name":
            return self.programme.name if self.programme else "Programme Name"
        values = {
            "title": lambda: movie.title,
            "director": lambda: movie.director,
            "year": lambda: str(movie.year),
            "certification": lambda: movie.certification,
            "runtime": lambda: f"{movie.runtime} min",
        }
        return values[field]() if field in values else None

    def _render_image(self, image: Image.Image, element: dict) -> None:
        image_path = element.get("path")
        if not image_path:
            return

        if image_path.startswith(settings.MEDIA_URL):
            relative_path = image_path[len(settings.MEDIA_URL) :]
            image_path = os.path.join(settings.MEDIA_ROOT, relative_path)

        if not os.path.exists(image_path):
            logger.warning(f"Image not found: {image_path}")
            return

        try:
            custom_img = Image.open(image_path)
            width, height = element.get("width"), element.get("height")
            if width and height:
                custom_img = custom_img.resize((int(width), int(height)), LANCZOS)
            self._paste(image, custom_img, element)
        except Exception as e:
            logger.error(f"Failed to render image {image_path}: {e}")

    def _render_rectangle(self, draw: ImageDraw.Draw, element: dict) -> None:
        x, y = int(element.get("x", 0)), int(element.get("y", 0))
        coords = [(x, y), (x + int(element.get("width", 100)), y + int(element.get("height", 100)))]
        color = (*self._parse_hex_rgb(element.get("color", "#FFFFFF")), int(255 * element.get("opacity", 1.0)))
        if element.get("fill", True):
            draw.rectangle(coords, fill=color)
        else:
            draw.rectangle(coords, outline=color, width=element.get("border_width", 1))

    @staticmethod
    def _resolve_font_path(font_name: str) -> str | None:
        """Resolve a font name to a loadable file, or None if nothing resolves."""
        font_name = BUNDLED_ALIASES.get(font_name, font_name)
        if bundled := BUNDLED_FONTS.get(font_name):
            path = bundled_fonts_dir() / bundled
            if path.exists():
                return str(path)

        try:
            ImageFont.truetype(font_name, 12)
            return font_name
        except OSError:
            pass

        font_alternatives = {
            "Arial": ["arial.ttf", "Arial.ttf", "DejaVuSans.ttf", "FreeSans.ttf"],
            "Helvetica": ["helvetica.ttf", "Helvetica.ttf", "DejaVuSans.ttf", "FreeSans.ttf"],
            "Times": ["times.ttf", "Times.ttf", "DejaVuSerif.ttf", "FreeSerif.ttf"],
            "Courier": ["cour.ttf", "Courier.ttf", "DejaVuSansMono.ttf", "LiberationMono-Regular.ttf", "FreeMono.ttf"],
        }
        font_files = font_alternatives.get(font_name, [f"{font_name}.ttf", f"{font_name.lower()}.ttf"])
        font_dirs = [
            "/usr/share/fonts/truetype/dejavu",
            "/usr/share/fonts/truetype/liberation",
            "/usr/share/fonts/truetype/freefont",
            f"/usr/share/fonts/truetype/{font_name.lower()}",
            "/usr/share/fonts/TTF",
            "/usr/share/fonts/liberation",
            "/System/Library/Fonts",
            "/Library/Fonts",
        ]
        for font_file in font_files:
            for font_dir in font_dirs:
                path = os.path.join(font_dir, font_file)
                if os.path.exists(path):
                    try:
                        ImageFont.truetype(path, 12)
                        return path
                    except OSError:
                        continue
        return None

    @classmethod
    def _load_font(cls, font_name: str, size: int) -> ImageFont.FreeTypeFont:
        """Also used by certification_service; falls back to PIL default."""
        path = cls._resolve_font_path(font_name)
        if path:
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                pass
        logger.warning(f"Font {font_name} not found, using default")
        return ImageFont.load_default()

    @classmethod
    def available_fonts(cls) -> list[dict]:
        return [{"name": name, "bundled": True} for name in sorted(BUNDLED_FONTS)] + [
            {"name": name, "bundled": False} for name in SYSTEM_FONT_CANDIDATES if cls._resolve_font_path(name)
        ]

    def _generate_video(self, image_path: Path, width: int, height: int, duration: int) -> Path:
        output_file = self.output_dir / f"programme_{self.programme.id}_title.mp4"
        programme = self.programme
        fade_in = getattr(programme, "title_fade_in", 0.0)
        fade_out = getattr(programme, "title_fade_out", 0.0)
        fades = []
        if fade_in > 0:
            fades.append(f"fade=t=in:st=0:d={fade_in}")
        if fade_out > 0:
            fades.append(f"fade=t=out:st={max(0, duration - fade_out)}:d={fade_out}")
        fade_suffix = "," + ",".join(fades) if fades else ""

        background = programme.title_background_type if programme.title_background_file else None
        if background in ("video", "image"):
            loop = "loop=loop=-1:size=1:start=0," if background == "image" else ""
            filter_complex = f"[0:v]{loop}scale={width}:{height}[bg];[bg][1:v]overlay{fade_suffix}"
            inputs = ["-i", usermedia_abs_path(programme.title_background_file), "-i", str(image_path)]
            length = ["-t", str(duration)]
        else:
            filter_complex = f"[0:v][1:v]overlay{fade_suffix}"
            color = programme.title_background_color.lstrip("#")
            inputs = ["-f", "lavfi", "-i", f"color=c=0x{color}:s={width}x{height}:d={duration}", "-i", str(image_path)]
            length = []
        cmd = [
            "ffmpeg",
            "-y",
            *inputs,
            "-filter_complex",
            filter_complex,
            *length,
            *["-c:v", "libx264", "-preset", "fast", "-pix_fmt", "yuv420p", str(output_file)],
        ]

        try:
            logger.info(f"Running ffmpeg: {' '.join(cmd)}")
            subprocess.run(cmd, check=True, capture_output=True, timeout=120)
            logger.info(f"Generated title video: {output_file}")
            return output_file
        except subprocess.CalledProcessError as e:
            logger.error(f"FFmpeg failed: {e.stderr.decode()}")
            raise Exception(f"Video generation failed: {e.stderr.decode()}") from e
        except subprocess.TimeoutExpired as e:
            raise Exception("Video generation timed out") from e
