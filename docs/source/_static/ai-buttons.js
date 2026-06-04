/* pyGigEVision docs: AI-assistant dropdown.
 * Injects a small icon-button + dropdown into the article header toolbar,
 * matching the existing download-dropdown style (Bootstrap 5 / Font Awesome).
 * Dropdown entries:
 *   - View as markdown    -> navigates to the .md URL (inline preview)
 *   - Copy as markdown    -> fetches the .md and writes it to clipboard
 *   - Open in Claude      -> opens claude.ai with a prefilled prompt
 *   - Open in ChatGPT     -> opens chatgpt.com with a prefilled prompt
 */
(function () {
    "use strict";

    function getMarkdownUrl() {
        const loc = window.location;
        let path = loc.pathname;
        if (path.endsWith(".html")) {
            return loc.origin + path.slice(0, -5) + ".md";
        }
        if (path.endsWith("/")) {
            return loc.origin + path + "index.md";
        }
        return loc.origin + path + ".md";
    }

    function buildPrompt(mdUrl) {
        return (
            "I'm reading the pyGigEVision documentation at " +
            mdUrl +
            ". Please fetch that page and help me with my question."
        );
    }

    async function copyAsMarkdown(linkEl, mdUrl) {
        const textSpan = linkEl.querySelector(".btn__text-container");
        const originalText = textSpan ? textSpan.textContent : null;
        try {
            const resp = await fetch(mdUrl);
            if (!resp.ok) throw new Error("HTTP " + resp.status);
            const text = await resp.text();
            await navigator.clipboard.writeText(text);
            if (textSpan) textSpan.textContent = "Copied!";
            linkEl.classList.add("copied");
            setTimeout(function () {
                if (textSpan && originalText) textSpan.textContent = originalText;
                linkEl.classList.remove("copied");
            }, 1500);
        } catch (e) {
            console.error("ai-buttons: copy failed", e);
            if (textSpan) textSpan.textContent = "Copy failed";
            setTimeout(function () {
                if (textSpan && originalText) textSpan.textContent = originalText;
            }, 2000);
        }
    }

    function buildDropdown(mdUrl) {
        const prompt = encodeURIComponent(buildPrompt(mdUrl));
        const claudeUrl = "https://claude.ai/new?q=" + prompt;
        const gptUrl = "https://chatgpt.com/?q=" + prompt;

        const wrap = document.createElement("div");
        wrap.className = "dropdown dropdown-ai-buttons";
        wrap.innerHTML =
            '<button class="btn dropdown-toggle" type="button" data-bs-toggle="dropdown" ' +
            'aria-expanded="false" aria-label="Open in AI assistant" ' +
            'title="Open in AI assistant" data-bs-placement="bottom">' +
            '<i class="fas fa-robot"></i>' +
            "</button>" +
            '<ul class="dropdown-menu">' +
            '<li><a href="' + mdUrl + '"' +
            ' class="btn btn-sm dropdown-item">' +
            '<span class="btn__icon-container"><i class="fas fa-file-lines"></i></span>' +
            '<span class="btn__text-container">View as markdown</span></a></li>' +
            '<li><a href="#" data-ai-action="copy"' +
            ' class="btn btn-sm dropdown-item">' +
            '<span class="btn__icon-container"><i class="fas fa-clipboard"></i></span>' +
            '<span class="btn__text-container">Copy as markdown</span></a></li>' +
            '<li><a href="' + claudeUrl + '" target="_blank" rel="noopener"' +
            ' class="btn btn-sm dropdown-item">' +
            '<span class="btn__icon-container"><i class="fas fa-comment-dots"></i></span>' +
            '<span class="btn__text-container">Open in Claude</span></a></li>' +
            '<li><a href="' + gptUrl + '" target="_blank" rel="noopener"' +
            ' class="btn btn-sm dropdown-item">' +
            '<span class="btn__icon-container"><i class="fas fa-comments"></i></span>' +
            '<span class="btn__text-container">Open in ChatGPT</span></a></li>' +
            "</ul>";

        const copyLink = wrap.querySelector('[data-ai-action="copy"]');
        copyLink.addEventListener("click", function (ev) {
            ev.preventDefault();
            copyAsMarkdown(copyLink, mdUrl);
        });
        return wrap;
    }

    function inject() {
        const toolbar = document.querySelector(".article-header-buttons");
        if (!toolbar) return;
        if (toolbar.querySelector(".dropdown-ai-buttons")) return;

        const mdUrl = getMarkdownUrl();
        const dropdown = buildDropdown(mdUrl);

        // Insert AFTER the download dropdown if present, otherwise at the end.
        const downloadDropdown = toolbar.querySelector(".dropdown-download-buttons");
        if (downloadDropdown && downloadDropdown.parentNode === toolbar) {
            toolbar.insertBefore(dropdown, downloadDropdown.nextSibling);
        } else {
            toolbar.appendChild(dropdown);
        }
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", inject);
    } else {
        inject();
    }
})();
