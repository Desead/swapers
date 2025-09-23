from __future__ import annotations
import secrets
from typing import List, Tuple
from django.conf import settings
from django.utils.deprecation import MiddlewareMixin
from .services.site_setup import get_site_setup


def _split_sources(value: str | None) -> List[str]:
    if not value:
        return []
    raw = value.replace(",", " ").split()
    seen, out = set(), []
    for it in raw:
        it = it.strip()
        if not it:
            continue
        if it not in seen:
            seen.add(it)
            out.append(it)
    return out


def _strip_lang_prefix(path: str) -> Tuple[str, str | None]:
    """
    Убирает i18n-префикс языка из начала пути: "/ru/accounts/..." -> ("/accounts/...", "ru").
    Если префикса нет — вернёт исходный path и None.
    """
    path = path or "/"
    if not path.startswith("/"):
        path = "/" + path
    langs = getattr(settings, "LANGUAGES", (("ru", "Russian"), ("en", "English")))
    for code, _name in langs:
        pref = f"/{code}/"
        if path.startswith(pref):
            return path[len(pref)-1:] if path[len(pref)-1] == "/" else path[len(pref)-1:], code  # сохранить ведущий "/"
    return path, None


class CSPHeaderEnsureMiddleware(MiddlewareMixin):
    """
    Единый CSP, с профилями по маршрутам:
      - админка: CSP НЕ ставим;
      - accounts: relaxed (без strict-dynamic; разрешаем 'self' для скриптов);
      - остальное: strict (nonce + strict-dynamic).
    ДОЛЖНА стоять ПОСЛЕДНЕЙ в MIDDLEWARE.
    """

    def process_request(self, request):
        # Нужен nonce для strict-профиля и для стилей
        if not hasattr(request, "csp_nonce") or not request.csp_nonce:
            request.csp_nonce = secrets.token_urlsafe(16)

    def _is_admin_request(self, request) -> bool:
        try:
            setup = get_site_setup()
            admin_prefix = "/" + (getattr(setup, "admin_path", "admin") or "admin").strip("/") + "/"
        except Exception:
            admin_prefix = "/admin/"
        path = request.path or "/"
        return path.startswith(admin_prefix)

    def _is_accounts_request(self, request) -> bool:
        path = request.path or "/"
        path_wo_lang, _ = _strip_lang_prefix(path)
        return path_wo_lang.startswith("/accounts/")

    def _apply_extras_from_settings(self, policy: dict):
        def _ext(key: str, name: str):
            vals = getattr(settings, name, ())
            if vals:
                policy.setdefault(key, []).extend(list(vals))
        _ext("script-src", "CSP_SCRIPT_SRC")
        _ext("style-src", "CSP_STYLE_SRC")
        _ext("style-src-attr", "CSP_STYLE_SRC_ATTR")
        _ext("img-src", "CSP_IMG_SRC")
        _ext("font-src", "CSP_FONT_SRC")
        _ext("connect-src", "CSP_CONNECT_SRC")
        _ext("frame-ancestors", "CSP_FRAME_ANCESTORS")
        _ext("form-action", "CSP_FORM_ACTION")
        _ext("base-uri", "CSP_BASE_URI")
        _ext("object-src", "CSP_OBJECT_SRC")

    def _apply_extras_from_setup(self, policy: dict, setup):
        policy["script-src"].extend(_split_sources(getattr(setup, "csp_extra_script_src", "")))
        policy["style-src"].extend(_split_sources(getattr(setup, "csp_extra_style_src", "")))
        policy["img-src"].extend(_split_sources(getattr(setup, "csp_extra_img_src", "")))
        policy["connect-src"].extend(_split_sources(getattr(setup, "csp_extra_connect_src", "")))
        policy["frame-src"].extend(_split_sources(getattr(setup, "csp_extra_frame_src", "")))
        policy["font-src"].extend(_split_sources(getattr(setup, "csp_extra_font_src", "")))

    def _dedupe(self, policy: dict):
        for k, vals in list(policy.items()):
            seen, out = set(), []
            for v in vals:
                if v not in seen:
                    seen.add(v)
                    out.append(v)
            policy[k] = out

    def process_response(self, request, response):
        # 0) Админка — CSP убираем полностью
        if self._is_admin_request(request):
            for h in ("Content-Security-Policy", "Content-Security-Policy-Report-Only"):
                try:
                    del response.headers[h]
                except Exception:
                    pass
            return response

        setup = get_site_setup()
        nonce = getattr(request, "csp_nonce", None)
        nonce_token = f"'nonce-{nonce}'" if nonce else None

        # 1) Базовый каркас
        policy = {
            "default-src": ["'self'"],
            "img-src": ["'self'", "data:", "blob:"],
            "font-src": ["'self'", "data:"],
            "connect-src": ["'self'"],
            "frame-src": ["'self'"],
            "object-src": ["'none'"],
            "base-uri": ["'self'"],
            "frame-ancestors": ["'self'"],
            "form-action": ["'self'"],
        }

        # 2) Ветвим профиль
        if self._is_accounts_request(request):
            # RELAXED: без strict-dynamic, разрешаем self (и прочие источники)
            policy["script-src"] = ["'self'"]
            policy["style-src"] = ["'self'"]
            policy["style-src-attr"] = ["'unsafe-inline'"]
            # nonce для <style> пусть будет — не мешает
            if nonce_token:
                policy["style-src"].append(nonce_token)
        else:
            # STRICT: nonce + strict-dynamic
            policy["script-src"] = ["'self'", "'strict-dynamic'"]
            if nonce_token:
                policy["script-src"].append(nonce_token)
            policy["style-src"] = ["'self'"]
            if nonce_token:
                policy["style-src"].append(nonce_token)
            policy["style-src-attr"] = ["'unsafe-inline'"]  # чтобы не падали style="..."

        # 3) Подмешиваем источники из settings и SiteSetup
        self._apply_extras_from_settings(policy)
        self._apply_extras_from_setup(policy, setup)

        # 4) Удаляем дубли, собираем строку
        self._dedupe(policy)
        parts = [f"{k} {' '.join(v)}" for k, v in policy.items() if v]
        header_value = "; ".join(parts)

        header_name = (
            "Content-Security-Policy-Report-Only"
            if getattr(setup, "csp_report_only", False)
            else "Content-Security-Policy"
        )

        # 5) Сносим ранее выставленные CSP (в т.ч. от django-csp) и ставим наш
        for h in ("Content-Security-Policy", "Content-Security-Policy-Report-Only"):
            try:
                del response.headers[h]
            except Exception:
                pass
        response.headers[header_name] = header_value

        # report-uri по желанию
        report_uri = getattr(settings, "CSP_REPORT_URI", "")
        if report_uri:
            response.headers[header_name] += f"; report-uri {report_uri}"

        return response
