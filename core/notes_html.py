"""
Stage 10e — minimal-HTML rich notes.

Notes fields are edited via a contenteditable widget (see the shared
`.rn-editable` JS in templates/base.html) that only ever produces a tiny,
known set of tags: <b>, <i>, <u>, <br>. This module is the server-side
boundary that guarantees that's *actually* true no matter what the browser
sends — everything else gets stripped (text content is kept, just the
disallowed wrapping tags are dropped).

No third-party dependency: built on the stdlib html.parser.
"""
import html
from html.parser import HTMLParser

ALLOWED_TAGS = ('b', 'i', 'u')  # + br handled separately (it never nests)
_ALIASES = {'strong': 'b', 'em': 'i'}  # what execCommand sometimes emits


def _normalize(tag):
    tag = tag.lower()
    return _ALIASES.get(tag, tag)


class _NotesSanitizer(HTMLParser):
    """Keeps only <b>/<i>/<u>/<br>, drops everything else but keeps the text
    inside dropped tags, and always emits well-formed (balanced) output."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out = []
        self.stack = []

    def handle_starttag(self, tag, attrs):
        tag = _normalize(tag)
        if tag == 'br':
            self.out.append('<br>')
        elif tag in ALLOWED_TAGS:
            self.out.append('<%s>' % tag)
            self.stack.append(tag)
        # anything else: dropped (children are still processed/kept)

    def handle_endtag(self, tag):
        tag = _normalize(tag)
        if tag not in ALLOWED_TAGS or tag not in self.stack:
            return
        # close down to and including the matching tag (auto-fixes nesting)
        while self.stack:
            top = self.stack.pop()
            self.out.append('</%s>' % top)
            if top == tag:
                break

    def handle_data(self, data):
        self.out.append(html.escape(data))

    def close(self):
        super().close()
        while self.stack:
            self.out.append('</%s>' % self.stack.pop())

    def get_html(self):
        return ''.join(self.out)


class _NotesTruncator(HTMLParser):
    """Like the sanitizer, but stops once `limit` visible text characters
    have been emitted, closing any still-open tag and appending an ellipsis.
    Never cuts a tag in half."""

    def __init__(self, limit):
        super().__init__(convert_charrefs=True)
        self.limit = max(int(limit), 0)
        self.out = []
        self.stack = []
        self.count = 0
        self.truncated = False

    def handle_starttag(self, tag, attrs):
        if self.truncated:
            return
        tag = _normalize(tag)
        if tag == 'br':
            if self.count >= self.limit:
                self.truncated = True
                return
            self.out.append('<br>')
        elif tag in ALLOWED_TAGS:
            self.out.append('<%s>' % tag)
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if self.truncated:
            return
        tag = _normalize(tag)
        if tag not in ALLOWED_TAGS or tag not in self.stack:
            return
        while self.stack:
            top = self.stack.pop()
            self.out.append('</%s>' % top)
            if top == tag:
                break

    def handle_data(self, data):
        if self.truncated:
            return
        remaining = self.limit - self.count
        if remaining <= 0:
            self.truncated = True
            return
        if len(data) > remaining:
            data = data[:remaining]
            self.truncated = True
        self.count += len(data)
        self.out.append(html.escape(data))

    def close(self):
        super().close()
        while self.stack:
            self.out.append('</%s>' % self.stack.pop())
        if self.truncated:
            self.out.append('…')  # …

    def get_html(self):
        return ''.join(self.out)


def sanitize_notes_html(raw):
    """Whitelist-sanitize a notes HTML string down to <b>/<i>/<u>/<br> only.
    Call this in every notes form's clean_notes() before saving."""
    if not raw:
        return ''
    parser = _NotesSanitizer()
    parser.feed(raw)
    parser.close()
    return parser.get_html()


def truncate_notes_html(raw, length=60):
    """Sanitize + truncate to `length` visible characters for list-row /
    card previews. Safe to call on already-sanitized stored values."""
    if not raw:
        return ''
    parser = _NotesTruncator(length)
    parser.feed(raw)
    parser.close()
    return parser.get_html()


class _PlainTextExtractor(HTMLParser):
    """Drops every tag (keeping text), turning <br> into a real newline.
    Returns unescaped text — caller's template will auto-escape it once
    (e.g. for a title="" attribute), so this must NOT pre-escape."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out = []

    def handle_starttag(self, tag, attrs):
        if _normalize(tag) == 'br':
            self.out.append('\n')

    def handle_data(self, data):
        self.out.append(data)

    def get_text(self):
        return ''.join(self.out)


def plain_text_from_notes_html(raw):
    """Strip all tags, returning the plain visible text (e.g. for the
    native `title=""` tooltip attribute, which can't render markup)."""
    if not raw:
        return ''
    parser = _PlainTextExtractor()
    parser.feed(raw)
    parser.close()
    return parser.get_text()
