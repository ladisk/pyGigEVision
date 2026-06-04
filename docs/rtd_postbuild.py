"""Post-build step that produces the agent-friendly Markdown twin of the docs.

ReadTheDocs builds the HTML (and sphinx-llms-txt drops ``llms.txt`` /
``llms-full.txt`` into the HTML output during that build). This script runs
afterwards as a ``build.jobs.post_build`` entry and:

1. Builds the Markdown twin of every page with ``sphinx -b markdown``.
2. Converts the markdown-builder admonition headings (``#### WARNING``) into
   GitHub blockquote callouts (``> [!WARNING]``).
3. Copies every ``.md`` next to its ``.html`` so ``/page.md`` resolves at the
   same URL as ``/page.html``.
4. Rewrites the ``llms.txt`` / ``llms-full.txt`` links from the generated
   ``_sources/<page>.rst`` form to ``<page>.md``.

On ReadTheDocs the output dirs come from ``$READTHEDOCS_OUTPUT``. For local
verification, pass them explicitly::

    python docs/rtd_postbuild.py --html docs/build/html --md docs/build/md

Output is plain ASCII so the script does not crash on a cp1252 Windows console.
"""

import argparse
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SOURCE_DIR = os.path.join(HERE, "source")

# -- admonition conversion (ported from the OpenEOL docs overhaul) -----------
ADMON_MAP = {
    "NOTE": "NOTE",
    "HINT": "TIP",
    "TIP": "TIP",
    "WARNING": "WARNING",
    "IMPORTANT": "IMPORTANT",
    "CAUTION": "CAUTION",
    "ATTENTION": "WARNING",
    "DANGER": "CAUTION",
    "SEE ALSO": "NOTE",
}
ADMON_RE = re.compile(
    r"^#{1,6} (NOTE|HINT|TIP|WARNING|IMPORTANT|CAUTION|ATTENTION|DANGER|SEE ALSO)[ \t]*$"
)
HEADING_RE = re.compile(r"^#{1,6} ")
FENCE_RE = re.compile(r"^[ \t]*```")

# llms.txt links look like _sources/getting_started.rst -> getting_started.md
LLMS_URL_RE = re.compile(r"_sources/([^)\s]+?)\.(?:rst|md)")


def convert_admonitions(text):
    """Turn ``#### WARNING`` admonition headings into ``> [!WARNING]`` callouts.

    Code fences are tracked so a ``#`` comment inside a fenced block is not
    mistaken for a heading that ends the admonition body.
    """
    lines = text.splitlines()
    out = []
    i = 0
    outer_fence = False
    while i < len(lines):
        ln_cur = lines[i]
        if FENCE_RE.match(ln_cur):
            outer_fence = not outer_fence
            out.append(ln_cur)
            i += 1
            continue
        if outer_fence:
            out.append(ln_cur)
            i += 1
            continue
        m = ADMON_RE.match(ln_cur)
        if not m:
            out.append(ln_cur)
            i += 1
            continue
        admon = ADMON_MAP[m.group(1)]
        i += 1
        body = []
        inside_fence = False
        while i < len(lines):
            ln = lines[i]
            if FENCE_RE.match(ln):
                inside_fence = not inside_fence
                body.append(ln)
                i += 1
                continue
            if not inside_fence and HEADING_RE.match(ln):
                break
            body.append(ln)
            i += 1
        while body and not body[0].strip():
            body.pop(0)
        while body and not body[-1].strip():
            body.pop()
        out.append(f"> [!{admon}]")
        for ln in body:
            out.append(f"> {ln}" if ln.strip() else ">")
        out.append("")
    return "\n".join(out) + ("\n" if text.endswith("\n") else "")


def build_markdown(md_dir):
    """Build the Markdown twin into ``md_dir`` (wiped first for a clean run)."""
    if os.path.exists(md_dir):
        shutil.rmtree(md_dir)
    os.makedirs(md_dir, exist_ok=True)
    subprocess.run(
        [sys.executable, "-m", "sphinx", "-b", "markdown", SOURCE_DIR, md_dir],
        check=True,
    )


def postprocess_markdown(md_dir):
    """Rewrite every ``.md`` in place."""
    count = 0
    for root, _dirs, files in os.walk(md_dir):
        for name in files:
            if not name.endswith(".md"):
                continue
            path = os.path.join(root, name)
            with open(path, encoding="utf-8") as f:
                text = f.read()
            new = convert_admonitions(text)
            if new != text:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(new)
            count += 1
    print(f"postprocessed {count} markdown file(s)")


def copy_md_into_html(md_dir, html_dir):
    """Copy every ``.md`` into ``html_dir`` at the matching relative path."""
    count = 0
    for root, _dirs, files in os.walk(md_dir):
        for name in files:
            if not name.endswith(".md"):
                continue
            src = os.path.join(root, name)
            rel = os.path.relpath(src, md_dir)
            dst = os.path.join(html_dir, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)
            count += 1
    print(f"copied {count} markdown file(s) into {html_dir}")


def rewrite_llms_links(html_dir):
    """Point the llms index links at the ``.md`` URLs instead of ``_sources``."""
    for name in ("llms.txt", "llms-full.txt"):
        path = os.path.join(html_dir, name)
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as f:
            text = f.read()
        new = LLMS_URL_RE.sub(r"\1.md", text)
        if new != text:
            with open(path, "w", encoding="utf-8") as f:
                f.write(new)
            print(f"rewrote links in {name}")


def resolve_dirs(args):
    rtd_out = os.environ.get("READTHEDOCS_OUTPUT")
    html_dir = args.html or (os.path.join(rtd_out, "html") if rtd_out else None)
    md_dir = args.md or (os.path.join(rtd_out, "md") if rtd_out else None)
    if not html_dir or not md_dir:
        sys.exit(
            "Set $READTHEDOCS_OUTPUT or pass --html and --md "
            "(e.g. --html docs/build/html --md docs/build/md)."
        )
    return html_dir, md_dir


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--html", help="HTML output dir (default: $READTHEDOCS_OUTPUT/html)")
    parser.add_argument("--md", help="Markdown output dir (default: $READTHEDOCS_OUTPUT/md)")
    args = parser.parse_args()
    html_dir, md_dir = resolve_dirs(args)

    build_markdown(md_dir)
    postprocess_markdown(md_dir)
    copy_md_into_html(md_dir, html_dir)
    rewrite_llms_links(html_dir)
    print("rtd_postbuild: done")


if __name__ == "__main__":
    main()
