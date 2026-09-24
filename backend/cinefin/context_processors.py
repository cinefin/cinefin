"""Template context processors.

Only one server-rendered page remains (the login form — the UI proper is the
SPA under /app/), so this carries exactly what it renders: cinema branding
for the login screen. 500.html is deliberately context-free and 404.html is
self-contained.
"""


def cinema_config(request):
    """Expose cinema branding (name, web logo, accent colour) to templates."""
    cinema_name = "Cinefin"
    web_logo_url = None
    accent_color = None
    try:
        from cinefin.api.models import Settings
        from cinefin.api.utils import branding

        cinema_name = Settings.get("cinema.name") or "Cinefin"
        web_logo_url = branding.web_logo_url(Settings.get("cinema.web_logo_path"))
        # Re-validated here so a hand-edited DB value can never leak an
        # unexpected string into the inline <style> block.
        accent_color = branding.valid_accent_color(Settings.get("display.accent_color"))
    except Exception:
        pass
    return {
        "cinema_name": cinema_name,
        "cinema_web_logo_url": web_logo_url,
        "accent_color": accent_color,
    }
