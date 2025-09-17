import re
import pytest
from django.test import override_settings

# Выделяем содержимое <head>...</head>
HEAD_RE = re.compile(r"<head\b[^>]*>(?P<head>.*)</head>", re.IGNORECASE | re.DOTALL)

def _extract_head(html: str) -> str:
    m = HEAD_RE.search(html)
    assert m, "Не удалось найти <head>...</head> в ответе"
    return m.group("head")

@override_settings(DEBUG=False)
@pytest.mark.django_db
def test_head_inject_html_renders_raw_in_head(site_setup, get_home_html):
    # Вставляем несколько тегов (meta + link)
    site_setup.head_inject_html = (
        '<meta name="robots" content="noimageindex">\n'
        '<link rel="preconnect" href="https://fonts.gstatic.com/">'
    )
    site_setup.save(update_fields=["head_inject_html"])

    html = get_home_html()
    head = _extract_head(html)

    # Теги есть в <head> и не экранированы
    assert '<meta name="robots" content="noimageindex">' in head
    assert '<link rel="preconnect" href="https://fonts.gstatic.com/">' in head
    assert "&lt;meta" not in head and "&lt;link" not in head

    # Дубликатов нет
    assert head.count("noimageindex") == 1
    assert head.count("fonts.gstatic.com") == 1

@override_settings(DEBUG=False)
@pytest.mark.django_db
def test_head_inject_empty_produces_no_artifacts(site_setup, get_home_html):
    # Пустая вставка — ничего лишнего не добавляет
    site_setup.head_inject_html = ""
    site_setup.save(update_fields=["head_inject_html"])

    html = get_home_html()
    head = _extract_head(html)

    # Никаких следов наших тестовых фрагментов
    assert "noimageindex" not in head
    assert "fonts.gstatic.com" not in head

@override_settings(DEBUG=False)
@pytest.mark.django_db
def test_head_inject_updates_without_restart(site_setup, get_home_html):
    # 1) первая вставка
    site_setup.head_inject_html = '<meta name="test-flag" content="v1">'
    site_setup.save(update_fields=["head_inject_html"])
    head_v1 = _extract_head(get_home_html())
    assert 'content="v1"' in head_v1

    # 2) меняем на лету — должны увидеть обновление
    site_setup.head_inject_html = '<meta name="test-flag" content="v2">'
    site_setup.save(update_fields=["head_inject_html"])
    head_v2 = _extract_head(get_home_html())
    assert 'content="v2"' in head_v2
    assert 'content="v1"' not in head_v2
