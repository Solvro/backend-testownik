(function () {
    "use strict";

    var MONACO_ROOT = "https://cdn.jsdelivr.net/npm/monaco-editor@0.57.0/min";
    var PREVIEW_DELAY = 100;
    var DIFF_DELAY = 300;
    // Scroll positions are rounded differently by each pane.
    var SCROLL_TOLERANCE = 2;

    var monacoLoading = null;

    // Loaded on demand: Monaco's AMD loader would make marked and DOMPurify
    // register as AMD modules instead of globals if it ran before them.
    function loadMonaco() {
        if (!monacoLoading) {
            monacoLoading = new Promise(function (resolve, reject) {
                var script = document.createElement("script");
                script.src = MONACO_ROOT + "/vs/loader.js";
                script.onerror = reject;
                script.onload = function () {
                    window.require.config({ paths: { vs: MONACO_ROOT + "/vs" } });
                    window.require(
                        ["vs/editor/editor.main"],
                        function () {
                            resolve(window.monaco);
                        },
                        reject,
                    );
                };
                document.head.appendChild(script);
            });
        }
        return monacoLoading;
    }

    function isDark() {
        return document.documentElement.classList.contains("dark");
    }

    // Renders each top-level Markdown block separately to remember the source
    // line it came from. marked's output can carry raw HTML from the document,
    // so it only reaches innerHTML through DOMPurify.
    function renderPreview(source, preview) {
        if (!window.marked || !window.DOMPurify) {
            preview.textContent = source;
            return;
        }
        var line = 1;
        var html = window.marked.lexer(source).map(function (token) {
            var start = line;
            line += token.raw.split("\n").length - 1;
            if (token.type === "space" || token.type === "def") {
                return "";
            }
            return '<div class="legal-md-block" data-line="' + start + '">' + window.marked.parser([token]) + "</div>";
        });
        preview.innerHTML = window.DOMPurify.sanitize(html.join(""));
    }

    // Pairs of matching scroll positions, [editor, preview], in ascending order.
    function scrollPoints(editor, preview) {
        var maxEditor = Math.max(editor.getScrollHeight() - editor.getLayoutInfo().height, 0);
        var maxPreview = Math.max(preview.scrollHeight - preview.clientHeight, 0);
        var previewTop = preview.getBoundingClientRect().top - preview.scrollTop;
        var points = [[0, 0]];
        Array.prototype.forEach.call(preview.querySelectorAll("[data-line]"), function (block) {
            var element = block.firstElementChild;
            if (!element) {
                return;
            }
            var last = points[points.length - 1];
            var editorPosition = editor.getTopForLineNumber(Number(block.dataset.line));
            var previewPosition = element.getBoundingClientRect().top - previewTop;
            if (
                editorPosition > last[0] &&
                previewPosition > last[1] &&
                editorPosition < maxEditor &&
                previewPosition < maxPreview
            ) {
                points.push([editorPosition, previewPosition]);
            }
        });
        points.push([maxEditor, maxPreview]);
        return points;
    }

    function translate(points, value, from) {
        var to = from === 0 ? 1 : 0;
        for (var i = 1; i < points.length; i += 1) {
            var start = points[i - 1];
            var end = points[i];
            if (value <= end[from]) {
                var span = end[from] - start[from];
                var progress = span > 0 ? (value - start[from]) / span : 0;
                return start[to] + Math.max(progress, 0) * (end[to] - start[to]);
            }
        }
        return points[points.length - 1][to];
    }

    // Keeps the same part of the document visible in both panes. A scroll caused
    // by following the other pane is recognised by its position and not echoed.
    function syncScroll(monaco, editor, preview) {
        var expectedEditor = null;
        var expectedPreview = null;

        function followEditor() {
            var target = translate(scrollPoints(editor, preview), editor.getScrollTop(), 0);
            if (Math.abs(preview.scrollTop - target) >= 1) {
                expectedPreview = target;
                preview.scrollTop = target;
            }
        }

        function followPreview() {
            var target = translate(scrollPoints(editor, preview), preview.scrollTop, 1);
            if (Math.abs(editor.getScrollTop() - target) >= 1) {
                expectedEditor = target;
                editor.setScrollTop(target, monaco.editor.ScrollType.Immediate);
            }
        }

        editor.onDidScrollChange(function (event) {
            if (!event.scrollTopChanged) {
                return;
            }
            var echoed = expectedEditor !== null && Math.abs(event.scrollTop - expectedEditor) <= SCROLL_TOLERANCE;
            expectedEditor = null;
            if (!echoed) {
                followEditor();
            }
        });
        preview.addEventListener("scroll", function () {
            var echoed = expectedPreview !== null && Math.abs(preview.scrollTop - expectedPreview) <= SCROLL_TOLERANCE;
            expectedPreview = null;
            if (!echoed) {
                followPreview();
            }
        });
        return followEditor;
    }

    function createEditor(monaco, host, value, readOnly) {
        var editor = monaco.editor.create(host, {
            value: value,
            language: "markdown",
            theme: isDark() ? "vs-dark" : "vs",
            readOnly: readOnly,
            automaticLayout: true,
            wordWrap: "on",
            fontSize: 13,
            lineHeight: 21,
            minimap: { enabled: false },
            stickyScroll: { enabled: false },
            scrollBeyondLastLine: false,
            scrollbar: { alwaysConsumeMouseWheel: false },
            quickSuggestions: false,
            wordBasedSuggestions: "off",
            // Polish typography is flagged as suspicious otherwise.
            unicodeHighlight: { ambiguousCharacters: false, invisibleCharacters: false },
        });
        new MutationObserver(function () {
            monaco.editor.setTheme(isDark() ? "vs-dark" : "vs");
            host.closest(".blog-md-editor").classList.toggle("md-dark", isDark());
        }).observe(document.documentElement, { attributes: true, attributeFilter: ["class"] });
        return editor;
    }

    function createHost(fallback) {
        var host = document.createElement("div");
        host.className = "legal-monaco";
        fallback.parentNode.insertBefore(host, fallback);
        return host;
    }

    // Published version: read-only, built the first time the full text is opened.
    function initContentView(section) {
        var toggle = section.querySelector("[data-legal-toggle]");
        var excerpt = section.querySelector("[data-legal-excerpt]");
        var full = section.querySelector("[data-legal-full]");
        var preview = section.querySelector("[data-legal-preview]");
        var sourceElement = section.querySelector("[data-legal-source]");
        var source = sourceElement.textContent;
        var built = false;

        full.classList.toggle("md-dark", isDark());

        function build() {
            built = true;
            renderPreview(source, preview);
            loadMonaco()
                .then(function (monaco) {
                    var editor = createEditor(monaco, createHost(sourceElement), source, true);
                    sourceElement.hidden = true;
                    syncScroll(monaco, editor, preview);
                })
                .catch(function () {
                    /* The plain text stays visible. */
                });
        }

        toggle.addEventListener("click", function () {
            var expand = full.hidden;
            full.hidden = !expand;
            excerpt.hidden = expand;
            if (expand && !built) {
                build();
            }
            toggle.textContent = expand ? "Hide full content" : "Show full content";
            toggle.setAttribute("aria-expanded", expand ? "true" : "false");
        });
    }

    // Refreshes the comparison with the text being edited, which isn't saved yet.
    function createLiveDiff(textarea, section) {
        var form = textarea.form;
        var status = document.querySelector("[data-legal-diff-status]");
        var kind = form.querySelector('[name="kind"]');
        var token = form.querySelector('[name="csrfmiddlewaretoken"]');
        var compare = new URLSearchParams(window.location.search).get("compare") || "";
        var controller = null;
        var timer = null;

        function showStatus(message) {
            status.textContent = message;
            status.hidden = !message;
        }

        function unsavedNotice() {
            var isUnsaved = textarea.value.replace(/\r/g, "") !== textarea.defaultValue.replace(/\r/g, "");
            return isUnsaved ? "Includes unsaved edits. Publishing uses the saved text, so save first." : "";
        }

        function refresh() {
            window.clearTimeout(timer);
            if (controller) {
                controller.abort();
            }
            var request = new AbortController();
            controller = request;
            fetch(section.dataset.url, {
                method: "POST",
                credentials: "same-origin",
                // An expired session redirects to the login page, which isn't a diff.
                redirect: "manual",
                signal: request.signal,
                headers: { "X-CSRFToken": token.value },
                body: new URLSearchParams({ kind: kind.value, content: textarea.value, compare: compare }),
            })
                .then(function (response) {
                    if (!response.ok) {
                        throw new Error("Unexpected response");
                    }
                    return response.text();
                })
                .then(function (html) {
                    section.innerHTML = html;
                    showStatus(unsavedNotice());
                })
                .catch(function (error) {
                    if (error.name !== "AbortError") {
                        showStatus("The comparison couldn't be refreshed. Reload the page if this continues.");
                    }
                });
        }

        section.addEventListener("click", function (event) {
            var link = event.target.closest("[data-compare]");
            if (link) {
                // Following the link would reload the page and lose unsaved edits.
                event.preventDefault();
                compare = link.dataset.compare;
                refresh();
            }
        });
        kind.addEventListener("change", function () {
            compare = "";
            refresh();
        });
        refresh();

        return function refreshSoon() {
            window.clearTimeout(timer);
            timer = window.setTimeout(refresh, DIFF_DELAY);
        };
    }

    function initDraftEditor(textarea) {
        var container = document.createElement("div");
        container.className = "blog-md-editor legal-editor";
        container.classList.toggle("md-dark", isDark());
        var wrapper = document.createElement("div");
        wrapper.className = "blog-md-wrapper";
        var preview = document.createElement("div");
        preview.className = "blog-md-preview";

        textarea.parentNode.insertBefore(container, textarea);
        container.appendChild(wrapper);
        wrapper.appendChild(textarea);
        wrapper.appendChild(preview);

        var section = document.querySelector("[data-legal-diff][data-url]");
        var refreshDiff = section ? createLiveDiff(textarea, section) : function () {};
        var followEditor = function () {};
        var previewTimer = null;

        function onEdit() {
            refreshDiff();
            window.clearTimeout(previewTimer);
            previewTimer = window.setTimeout(function () {
                renderPreview(textarea.value, preview);
                followEditor();
            }, PREVIEW_DELAY);
        }

        renderPreview(textarea.value, preview);
        textarea.addEventListener("input", onEdit);

        loadMonaco()
            .then(function (monaco) {
                var editor = createEditor(monaco, createHost(textarea), textarea.value, false);
                // A hidden required field would silently block submitting the form.
                textarea.required = false;
                textarea.hidden = true;
                followEditor = syncScroll(monaco, editor, preview);
                editor.onDidChangeModelContent(function () {
                    textarea.value = editor.getValue();
                    onEdit();
                });
            })
            .catch(function () {
                /* The plain textarea keeps working. */
            });
    }

    // Each document type has its own notice option, so only that one is offered.
    function initNoticeFields() {
        var kind = document.getElementById("id_kind");
        var options = {
            terms: document.getElementById("id_requires_acceptance"),
            privacy: document.getElementById("id_notify_users"),
        };
        if (!kind || !options.terms || !options.privacy) {
            return;
        }

        function update() {
            Object.keys(options).forEach(function (type) {
                var isOffered = type === kind.value;
                // Unfold keeps the label and the input in two columns of one row.
                var row = options[type].closest(".grow").parentNode;
                row.style.display = isOffered ? "" : "none";
                if (!isOffered) {
                    options[type].checked = false;
                }
            });
        }

        kind.addEventListener("change", update);
        update();
    }

    function start() {
        initNoticeFields();
        Array.prototype.forEach.call(document.querySelectorAll("[data-legal-content]"), initContentView);
        Array.prototype.forEach.call(document.querySelectorAll("textarea.blog-markdown-editor"), initDraftEditor);
    }

    if (document.readyState !== "loading") {
        start();
    } else {
        document.addEventListener("DOMContentLoaded", start);
    }
})();
