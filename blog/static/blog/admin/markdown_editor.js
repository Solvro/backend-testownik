(function () {
    "use strict";

    var STORAGE_KEY = "blogMarkdownPreviewTheme";

    function renderPreview(textarea, preview) {
        if (window.marked && typeof window.marked.parse === "function") {
            preview.innerHTML = window.marked.parse(textarea.value || "");
        } else {
            // marked.js not loaded (e.g. offline) — fall back to raw text.
            preview.textContent = textarea.value || "";
        }
    }

    function initialTheme() {
        var stored = null;
        try {
            stored = window.localStorage.getItem(STORAGE_KEY);
        } catch (e) {
            stored = null;
        }
        if (stored === "dark" || stored === "light") {
            return stored;
        }
        // Default to the admin's current theme.
        return document.documentElement.classList.contains("dark") ? "dark" : "light";
    }

    function applyTheme(container, button, theme) {
        var isDark = theme === "dark";
        container.classList.toggle("md-dark", isDark);
        button.textContent = isDark ? "🌙" : "☀";
        button.setAttribute("aria-pressed", isDark ? "true" : "false");
        button.setAttribute("aria-label", isDark ? "Motyw podglądu: ciemny" : "Motyw podglądu: jasny");
    }

    function buildToggle(container) {
        var toolbar = document.createElement("div");
        toolbar.className = "blog-md-toolbar";

        var button = document.createElement("button");
        button.type = "button";
        button.className = "blog-md-theme-toggle";
        button.title = "Przełącz motyw podglądu (jasny / ciemny)";

        var theme = initialTheme();
        applyTheme(container, button, theme);

        button.addEventListener("click", function () {
            theme = container.classList.contains("md-dark") ? "light" : "dark";
            applyTheme(container, button, theme);
            try {
                window.localStorage.setItem(STORAGE_KEY, theme);
            } catch (e) {
                /* ignore storage failures (private mode etc.) */
            }
        });

        toolbar.appendChild(button);
        return toolbar;
    }

    function enhance(textarea) {
        if (textarea.dataset.mdInitialized) {
            return;
        }
        textarea.dataset.mdInitialized = "1";

        var container = document.createElement("div");
        container.className = "blog-md-editor";

        var wrapper = document.createElement("div");
        wrapper.className = "blog-md-wrapper";

        var preview = document.createElement("div");
        preview.className = "blog-md-preview";

        textarea.parentNode.insertBefore(container, textarea);
        container.appendChild(buildToggle(container));
        container.appendChild(wrapper);
        wrapper.appendChild(textarea);
        wrapper.appendChild(preview);

        renderPreview(textarea, preview);
        textarea.addEventListener("input", function () {
            renderPreview(textarea, preview);
        });
    }

    function init() {
        var editors = document.querySelectorAll("textarea.blog-markdown-editor");
        Array.prototype.forEach.call(editors, enhance);
    }

    if (document.readyState !== "loading") {
        init();
    } else {
        document.addEventListener("DOMContentLoaded", init);
    }
})();
