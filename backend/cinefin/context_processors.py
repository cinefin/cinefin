"""Template context: cinema branding for the login page (the only server-rendered page)."""


def cinema_config(request):
    cinema_name, web_logo_url, accent_color = "Cinefin", None, None
    try:
        from cinefin.api.models import Settings
        from cinefin.api.utils import branding

        cinema_name = Settings.get("cinema.name") or "Cinefin"
        web_logo_url = branding.web_logo_url(Settings.get("cinema.web_logo_path"))
        # Re-validated so a hand-edited DB value can't leak into the inline <style>.
        accent_color = branding.valid_accent_color(Settings.get("display.accent_color"))
    except Exception:  # noqa: BLE001 - the login page must render even with a broken DB
        pass
    return {"cinema_name": cinema_name, "cinema_web_logo_url": web_logo_url, "accent_color": accent_color}
