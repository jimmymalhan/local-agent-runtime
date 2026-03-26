#!/usr/bin/env python3
"""SiteGen CLI: Markdown to HTML static site generator with frontmatter support."""

import os
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path


def parse_frontmatter(text):
    """Parse YAML-like frontmatter from markdown text. Returns (metadata, body)."""
    metadata = {}
    body = text
    match = re.match(r'^---\s*\n(.*?)\n---\s*\n(.*)', text, re.DOTALL)
    if match:
        raw = match.group(1)
        body = match.group(2)
        for line in raw.strip().splitlines():
            key_val = line.split(':', 1)
            if len(key_val) == 2:
                key = key_val[0].strip()
                val = key_val[1].strip()
                if key == 'tags':
                    val = [t.strip().strip('"').strip("'") for t in val.strip('[]').split(',')]
                else:
                    val = val.strip('"').strip("'")
                metadata[key] = val
    return metadata, body


def markdown_to_html(md):
    """Convert a subset of markdown to HTML."""
    lines = md.split('\n')
    html_lines = []
    in_code_block = False
    in_ul = False
    in_ol = False
    in_paragraph = False

    def close_lists():
        nonlocal in_ul, in_ol
        result = []
        if in_ul:
            result.append('</ul>')
            in_ul = False
        if in_ol:
            result.append('</ol>')
            in_ol = False
        return result

    def close_paragraph():
        nonlocal in_paragraph
        result = []
        if in_paragraph:
            result.append('</p>')
            in_paragraph = False
        return result

    def inline_format(text):
        # Images
        text = re.sub(r'!\[([^\]]*)\]\(([^)]+)\)', r'<img src="\2" alt="\1">', text)
        # Links
        text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2">\1</a>', text)
        # Bold
        text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
        text = re.sub(r'__(.+?)__', r'<strong>\1</strong>', text)
        # Italic
        text = re.sub(r'\*(.+?)\*', r'<em>\1</em>', text)
        text = re.sub(r'_(.+?)_', r'<em>\1</em>', text)
        # Inline code
        text = re.sub(r'`([^`]+)`', r'<code>\1</code>', text)
        return text

    for line in lines:
        # Fenced code blocks
        if line.strip().startswith('```'):
            if in_code_block:
                html_lines.append('</code></pre>')
                in_code_block = False
            else:
                html_lines.extend(close_paragraph())
                html_lines.extend(close_lists())
                lang = line.strip()[3:].strip()
                cls = f' class="language-{lang}"' if lang else ''
                html_lines.append(f'<pre><code{cls}>')
                in_code_block = True
            continue

        if in_code_block:
            html_lines.append(line.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;'))
            continue

        stripped = line.strip()

        # Blank line
        if not stripped:
            html_lines.extend(close_paragraph())
            html_lines.extend(close_lists())
            continue

        # Headings
        heading_match = re.match(r'^(#{1,6})\s+(.+)', stripped)
        if heading_match:
            html_lines.extend(close_paragraph())
            html_lines.extend(close_lists())
            level = len(heading_match.group(1))
            content = inline_format(heading_match.group(2))
            html_lines.append(f'<h{level}>{content}</h{level}>')
            continue

        # Horizontal rule
        if re.match(r'^(---|\*\*\*|___)\s*$', stripped):
            html_lines.extend(close_paragraph())
            html_lines.extend(close_lists())
            html_lines.append('<hr>')
            continue

        # Blockquote
        if stripped.startswith('>'):
            html_lines.extend(close_paragraph())
            html_lines.extend(close_lists())
            content = inline_format(stripped[1:].strip())
            html_lines.append(f'<blockquote><p>{content}</p></blockquote>')
            continue

        # Unordered list
        ul_match = re.match(r'^[-*+]\s+(.+)', stripped)
        if ul_match:
            html_lines.extend(close_paragraph())
            if not in_ul:
                html_lines.extend(close_lists())
                html_lines.append('<ul>')
                in_ul = True
            html_lines.append(f'<li>{inline_format(ul_match.group(1))}</li>')
            continue

        # Ordered list
        ol_match = re.match(r'^\d+\.\s+(.+)', stripped)
        if ol_match:
            html_lines.extend(close_paragraph())
            if not in_ol:
                html_lines.extend(close_lists())
                html_lines.append('<ol>')
                in_ol = True
            html_lines.append(f'<li>{inline_format(ol_match.group(1))}</li>')
            continue

        # Paragraph text
        if not in_paragraph:
            html_lines.append('<p>')
            in_paragraph = True
        html_lines.append(inline_format(stripped))

    html_lines.extend(close_paragraph())
    html_lines.extend(close_lists())

    return '\n'.join(html_lines)


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 800px; margin: 0 auto; padding: 2rem; line-height: 1.6; color: #333; }}
        h1, h2, h3 {{ color: #1a1a1a; }}
        a {{ color: #0066cc; text-decoration: none; }}
        a:hover {{ text-decoration: underline; }}
        pre {{ background: #f5f5f5; padding: 1rem; border-radius: 4px; overflow-x: auto; }}
        code {{ background: #f5f5f5; padding: 0.2em 0.4em; border-radius: 3px; font-size: 0.9em; }}
        pre code {{ background: none; padding: 0; }}
        blockquote {{ border-left: 4px solid #ddd; margin-left: 0; padding-left: 1rem; color: #666; }}
        .tags {{ margin-top: 0.5rem; }}
        .tag {{ display: inline-block; background: #e8f0fe; color: #1a73e8; padding: 0.2em 0.6em; border-radius: 12px; font-size: 0.85em; margin-right: 0.4em; }}
        .post-meta {{ color: #666; font-size: 0.9em; margin-bottom: 1rem; }}
        .post-list {{ list-style: none; padding: 0; }}
        .post-list li {{ padding: 1rem 0; border-bottom: 1px solid #eee; }}
        .post-list .post-date {{ color: #888; font-size: 0.85em; }}
        hr {{ border: none; border-top: 1px solid #ddd; margin: 2rem 0; }}
        nav {{ margin-bottom: 2rem; }}
        nav a {{ margin-right: 1rem; }}
    </style>
</head>
<body>
    <nav><a href="index.html">Home</a></nav>
    {content}
</body>
</html>"""


def render_post(metadata, body_html):
    """Render a single post page."""
    title = metadata.get('title', 'Untitled')
    date = metadata.get('date', '')
    tags = metadata.get('tags', [])

    meta_html = ''
    if date:
        meta_html += f'<div class="post-meta">{date}</div>'
    if tags:
        tags_html = ''.join(f'<span class="tag">{t}</span>' for t in tags)
        meta_html += f'<div class="tags">{tags_html}</div>'

    content = f'<h1>{title}</h1>\n{meta_html}\n{body_html}'
    return HTML_TEMPLATE.format(title=title, content=content)


def render_index(posts):
    """Render the index page with a list of all posts."""
    posts_sorted = sorted(posts, key=lambda p: p.get('date', ''), reverse=True)

    items = []
    for post in posts_sorted:
        title = post.get('title', 'Untitled')
        date = post.get('date', '')
        slug = post['slug']
        tags = post.get('tags', [])
        tags_html = ''.join(f'<span class="tag">{t}</span>' for t in tags) if tags else ''
        date_html = f'<span class="post-date">{date}</span>' if date else ''
        items.append(f'<li><a href="{slug}.html">{title}</a> {date_html}<div class="tags">{tags_html}</div></li>')

    post_list = '\n'.join(items) if items else '<li>No posts yet.</li>'
    content = f'<h1>Posts</h1>\n<ul class="post-list">\n{post_list}\n</ul>'
    return HTML_TEMPLATE.format(title='Home', content=content)


def build_site(input_dir, output_dir):
    """Build the static site from markdown files."""
    input_path = Path(input_dir)
    output_path = Path(output_dir)

    if not input_path.exists():
        print(f"Error: Input directory '{input_dir}' does not exist.", file=sys.stderr)
        sys.exit(1)

    if output_path.exists():
        shutil.rmtree(output_path)
    output_path.mkdir(parents=True)

    md_files = sorted(input_path.glob('*.md'))
    if not md_files:
        print(f"Warning: No .md files found in '{input_dir}'.", file=sys.stderr)

    posts = []
    for md_file in md_files:
        raw = md_file.read_text(encoding='utf-8')
        metadata, body = parse_frontmatter(raw)
        body_html = markdown_to_html(body)
        slug = md_file.stem

        metadata['slug'] = slug
        posts.append(metadata)

        page_html = render_post(metadata, body_html)
        (output_path / f'{slug}.html').write_text(page_html, encoding='utf-8')
        print(f"  Generated {slug}.html")

    index_html = render_index(posts)
    (output_path / 'index.html').write_text(index_html, encoding='utf-8')
    print(f"  Generated index.html")
    print(f"Built {len(posts)} post(s) -> {output_path}/")
    return posts


def main():
    """CLI entry point."""
    input_dir = sys.argv[1] if len(sys.argv) > 1 else 'input'
    output_dir = sys.argv[2] if len(sys.argv) > 2 else 'output'
    print(f"SiteGen: {input_dir}/ -> {output_dir}/")
    build_site(input_dir, output_dir)


if __name__ == '__main__':
    import tempfile

    # --- Self-test with assertions ---
    print("Running self-tests...\n")

    # Test 1: parse_frontmatter
    fm_text = """---
title: Hello World
date: 2025-01-15
tags: [python, static-sites]
---

# Welcome

This is a test post."""
    meta, body = parse_frontmatter(fm_text)
    assert meta['title'] == 'Hello World', f"Expected 'Hello World', got {meta['title']}"
    assert meta['date'] == '2025-01-15', f"Expected '2025-01-15', got {meta['date']}"
    assert meta['tags'] == ['python', 'static-sites'], f"Tags mismatch: {meta['tags']}"
    assert body.strip().startswith('# Welcome'), f"Body mismatch: {body[:30]}"
    print("PASS: parse_frontmatter")

    # Test 2: markdown_to_html basics
    md = "# Title\n\nHello **world** and *italic*.\n\n- item1\n- item2\n\n1. first\n2. second\n\n> quote here\n\n```python\nprint('hi')\n```\n\n[link](http://example.com)\n"
    html = markdown_to_html(md)
    assert '<h1>Title</h1>' in html, f"Missing h1: {html}"
    assert '<strong>world</strong>' in html, f"Missing bold: {html}"
    assert '<em>italic</em>' in html, f"Missing italic: {html}"
    assert '<ul>' in html and '<li>item1</li>' in html, f"Missing ul: {html}"
    assert '<ol>' in html and '<li>first</li>' in html, f"Missing ol: {html}"
    assert '<blockquote>' in html, f"Missing blockquote: {html}"
    assert '<pre><code class="language-python">' in html, f"Missing code block: {html}"
    assert '<a href="http://example.com">link</a>' in html, f"Missing link: {html}"
    print("PASS: markdown_to_html")

    # Test 3: Full site build
    with tempfile.TemporaryDirectory() as tmpdir:
        in_dir = Path(tmpdir) / 'input'
        out_dir = Path(tmpdir) / 'output'
        in_dir.mkdir()

        (in_dir / 'first-post.md').write_text("""---
title: First Post
date: 2025-03-01
tags: [intro, test]
---

# My First Post

Hello from SiteGen! This has **bold** and *italic* text.

- Bullet one
- Bullet two
""", encoding='utf-8')

        (in_dir / 'second-post.md').write_text("""---
title: Second Post
date: 2025-03-10
tags: [update]
---

# Another Post

Some `inline code` and a [link](https://example.com).

```js
console.log("hello");
```
""", encoding='utf-8')

        (in_dir / 'no-frontmatter.md').write_text("""# Plain Post

No frontmatter here, just markdown.
""", encoding='utf-8')

        posts = build_site(str(in_dir), str(out_dir))

        # Verify output files exist
        assert (out_dir / 'index.html').exists(), "index.html missing"
        assert (out_dir / 'first-post.html').exists(), "first-post.html missing"
        assert (out_dir / 'second-post.html').exists(), "second-post.html missing"
        assert (out_dir / 'no-frontmatter.html').exists(), "no-frontmatter.html missing"

        # Verify post count
        assert len(posts) == 3, f"Expected 3 posts, got {len(posts)}"

        # Verify index content
        index_content = (out_dir / 'index.html').read_text(encoding='utf-8')
        assert 'First Post' in index_content, "Index missing First Post"
        assert 'Second Post' in index_content, "Index missing Second Post"
        assert 'first-post.html' in index_content, "Index missing link to first-post"
        assert 'second-post.html' in index_content, "Index missing link to second-post"

        # Verify post content
        first_html = (out_dir / 'first-post.html').read_text(encoding='utf-8')
        assert '<title>First Post</title>' in first_html, "Missing title in first-post"
        assert '<strong>bold</strong>' in first_html, "Missing bold in first-post"
        assert '<em>italic</em>' in first_html, "Missing italic in first-post"
        assert 'intro' in first_html, "Missing tag 'intro' in first-post"
        assert '2025-03-01' in first_html, "Missing date in first-post"

        second_html = (out_dir / 'second-post.html').read_text(encoding='utf-8')
        assert '<code>inline code</code>' in second_html, "Missing inline code"
        assert 'language-js' in second_html, "Missing JS code block"
        assert '<a href="https://example.com">link</a>' in second_html, "Missing link"

        # Verify no-frontmatter post
        plain_html = (out_dir / 'no-frontmatter.html').read_text(encoding='utf-8')
        assert '<title>Untitled</title>' in plain_html, "Missing Untitled title"
        assert '<h1>Plain Post</h1>' in plain_html, "Missing heading in plain post"

        # Verify index sorts by date descending (Second Post before First Post)
        idx_second = index_content.index('Second Post')
        idx_first = index_content.index('First Post')
        assert idx_second < idx_first, "Index not sorted by date descending"

        print("PASS: full site build")

    print("\nAll tests passed.")
