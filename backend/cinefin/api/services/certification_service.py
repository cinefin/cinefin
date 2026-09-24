import logging
import os
import shutil
import subprocess
import tempfile

from django.conf import settings as django_settings
from PIL import Image, ImageDraw

from cinefin.api.models import Certification, Movie, Settings
from cinefin.api.utils.assets import rating_card_path, rating_card_video_path
from cinefin.api.utils.media_paths import to_usermedia_relative

logger = logging.getLogger(__name__)


def _ffmpeg_path() -> str:
    path = shutil.which("ffmpeg")
    if not path:
        raise FileNotFoundError("ffmpeg not found on PATH — install ffmpeg to generate certification cards")
    return path


class CertificationService:
    # Every generated card is encoded to this length; user-supplied static cards
    # (ratings/<system>/<cert>.mp4) may differ, but rundown/playlist displays assume this.
    CARD_SECONDS = 5

    # Systems whose card carries the film title are composed per-film from a
    # background. The rest (MPAA-style, which don't name the film) are static-only:
    # they play a ratings/<system>/<cert>.mp4 or are skipped.
    TITLE_CARD_SYSTEMS = {"BBFC"}

    @staticmethod
    def get_or_create_certification(movie: Movie) -> Certification | None:
        """Get or create the certification card for the active ratings system (None if unavailable)."""
        system = Settings.get_ratings_system()
        cert_value = movie.certificate_for(system) or movie.certification

        if not cert_value:
            logger.warning(f"Movie {movie.title} has no {system} certificate")
            return None

        if cert_value not in Settings.get_valid_ratings(system):
            logger.warning(
                f"Movie {movie.title} has certification '{cert_value}' which is not in the {system} set. Skipping certification block generation."
            )
            return None

        # A user-supplied static card (MEDIA_ROOT/ratings/<system>/<cert>.mp4) wins over
        # generation, even over a previously generated card, so dropping the file in takes effect at once.
        static_video = rating_card_video_path(system, cert_value)
        if static_video:
            certification, _ = Certification.objects.update_or_create(
                movie=movie,
                ratings_system=system,
                certification=cert_value,
                defaults={"file_path": to_usermedia_relative(static_video)},
            )
            logger.info(f"Using static {system} certification card for {movie.title}: {static_video}")
            return certification

        # MPAA-style systems don't name the film, so there's nothing to compose —
        # without a static card there is no card to play.
        if system not in CertificationService.TITLE_CARD_SYSTEMS:
            logger.warning(
                f"No static {system} card for '{cert_value}' ({system} cards are static-only) — skipping certification block."
            )
            return None

        existing_cert = Certification.objects.filter(
            movie=movie, ratings_system=system, certification=cert_value
        ).first()
        if existing_cert:
            logger.info(f"Using existing {system} certification for {movie.title}")
            return existing_cert

        try:
            cert_file_path = CertificationService._generate_certification_video(movie, system, cert_value)

            certification = Certification.objects.create(
                movie=movie,
                file_path=to_usermedia_relative(cert_file_path),
                certification=cert_value,
                ratings_system=system,
            )

            logger.info(f"Created {system} certification for {movie.title} with certification {cert_value}")
            return certification

        except Exception as e:
            logger.warning(f"Failed to generate certification for {movie.title}: {e}. Skipping certification block.")
            return None

    @staticmethod
    def _generate_certification_video(movie: Movie, system: str, cert: str) -> str:
        # Keyed by movie pk (plus system and cert) so a display-format switch or re-rating never
        # reuses the wrong card, and two local-file movies (both tmdbid=0) sharing a certificate
        # don't collide onto one card burnt with the first film's title.
        logger.info(f"Generating {system} video card for {movie.title} with certification {cert}")

        certifications_dir = os.path.join(django_settings.MEDIA_ROOT, "certifications")
        safe_cert = cert.replace("/", "-")
        cert_file = os.path.join(certifications_dir, f"{movie.pk}_{system}_{safe_cert}.mp4")

        if os.path.exists(cert_file):
            logger.info(f"{system} video card already exists for {movie.title}")
            return cert_file

        try:
            os.makedirs(os.path.dirname(cert_file), exist_ok=True)

            text_color = "white"
            background_path = rating_card_path(system, cert)
            if not background_path:
                raise FileNotFoundError(
                    f"No rating card background for '{cert}' — add one to MEDIA_ROOT/ratings/{cert}.jpg"
                )

            frame = CertificationService._compose_card_frame(
                background_path=background_path,
                title=movie.title.upper(),
                text_color=text_color,
            )

            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                frame_png = tmp.name
            try:
                frame.save(frame_png)
                CertificationService._encode_still_to_video(
                    frame_png, cert_file, duration=CertificationService.CARD_SECONDS
                )
            finally:
                os.unlink(frame_png)

            logger.info(f"{system} video card saved as {cert_file}")

            return cert_file

        except Exception as e:
            logger.error(f"Error generating certification video for {movie.title}: {e}")
            raise

    @staticmethod
    def _encode_still_to_video(image_path: str, output_path: str, duration: int) -> None:
        # Encode to a temp name and rename on success: a failed run must not leave a
        # partial file behind, or the exists-check above would keep serving it forever.
        partial = f"{output_path}.partial.mp4"
        cmd = [
            _ffmpeg_path(),
            "-y",
            "-loop",
            "1",
            "-i",
            image_path,
            "-t",
            str(duration),
            "-r",
            "24",
            "-c:v",
            "libx264",
            "-preset",
            "fast",
            # yuv420p needs even dimensions; user-supplied backgrounds may be odd
            "-vf",
            "scale=trunc(iw/2)*2:trunc(ih/2)*2",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            partial,
        ]
        try:
            subprocess.run(cmd, check=True, capture_output=True, timeout=120)
            os.replace(partial, output_path)
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"ffmpeg failed: {e.stderr.decode(errors='replace')}") from e
        except subprocess.TimeoutExpired as e:
            raise RuntimeError("ffmpeg timed out encoding certification card") from e
        finally:
            if os.path.exists(partial):
                os.unlink(partial)

    @staticmethod
    def _compose_card_frame(background_path: str, title: str | None = None, text_color: str = "white") -> Image.Image:
        """The card background with the film title burnt in. `title=None` leaves the
        background as-is (systems whose cards don't name the film)."""
        from cinefin.api.services.titlegen_service import TitleGenService

        frame = Image.open(background_path).convert("RGB")
        if not title:
            return frame

        draw = ImageDraw.Draw(frame)
        bar_x, bar_y, bar_w, bar_h = 122, 455, 1500, 60
        draw.rectangle((bar_x, bar_y, bar_x + bar_w, bar_y + bar_h), fill=(0, 0, 0))

        font_size = 70 if len(title) <= 37 else 36
        # "Courier Prime" resolves to the bundled CourierPrime.ttf so the card renders at the
        # requested size on minimal/Docker hosts; plain "Courier" would fall through to PIL's
        # fixed-size default bitmap font, making the title illegible.
        font = TitleGenService._load_font("Courier Prime", font_size)
        bbox = draw.textbbox((0, 0), title, font=font)
        text_height = bbox[3] - bbox[1]
        # bbox[1] compensates for ascent offset when centring vertically.
        text_y = bar_y + (bar_h - text_height) // 2 - bbox[1]
        draw.text((bar_x + 3, text_y), title, fill=text_color, font=font)
        return frame
