from .paths import resource_path


def get_html_page() -> str:
    return resource_path("templates/index.html").read_text(encoding="utf-8")


def get_waiting_page() -> str:
    return resource_path("templates/waiting.html").read_text(encoding="utf-8")
