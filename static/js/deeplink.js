(function () {
    function openUrl(url, target) {
        try {
            if (target === "_blank") {
                window.open(url, "_blank", "noopener,noreferrer");
            } else {
                window.location.assign(url);
            }
        } catch (e) {
            // на крайний случай
            window.location.href = url;
        }
    }

    function onClick(e) {
        var el = e.currentTarget;
        var url = el.getAttribute("data-href");
        if (!url) return;
        e.preventDefault();
        var target = el.getAttribute("data-target") || "_self";
        openUrl(url, target);
    }

    function onKey(e) {
        // поддержка Enter/Space как у ссылок
        if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            e.currentTarget.click();
        }
    }

    function onAuxClick(e) {
        // средняя кнопка мыши → открыть в новой вкладке
        if (e.button === 1) {
            var el = e.currentTarget;
            var url = el.getAttribute("data-href");
            if (!url) return;
            e.preventDefault();
            openUrl(url, "_blank");
        }
    }

    document.addEventListener("DOMContentLoaded", function () {
        // Делинк для скрытия реальных URL
        var nodes = document.querySelectorAll(".deeplink[data-href]");
        nodes.forEach(function (el) {
            el.addEventListener("click", onClick, false);
            el.addEventListener("keydown", onKey, false);
            el.addEventListener("auxclick", onAuxClick, false);
            // доступность
            if (!el.hasAttribute("tabindex")) el.setAttribute("tabindex", "0");
        });

        // Автосабмит переключателя языка (CSP-friendly — без inline JS)
        var sel = document.querySelector('[data-lang-switch]');
        if (sel && sel.form) {
            sel.addEventListener('change', function () {
                try { sel.form.submit(); } catch (e) { /* no-op */ }
            });
        }
    });
})();
