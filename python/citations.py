"""
Citation lookup and BibTeX handling.

Pure Python (stdlib only) so the same code backs both the web UI and the vim
plugin: web/app.py wraps these in HTTP routes, cite_cli.py wraps them in a
command-line interface that writer.vim calls.
"""

import json
import re
import urllib.parse
import urllib.request
from pathlib import Path

USER_AGENT = "Writer/1.0 (mailto:writer@writer.local)"
MAILTO = "writer@writer.local"
TIMEOUT = 15

# Preferred field order for formatted BibTeX
BIBTEX_FIELD_ORDER = [
    "author", "title", "journal", "volume", "number", "pages",
    "year", "month", "publisher", "doi", "issn", "url",
]


class DuplicateEntry(Exception):
    """Raised when a DOI is already present in the target .bib file."""


# --- Remote lookup ---

def _get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return json.loads(resp.read().decode())


def crossref_search(author="", title="", rows=10):
    """Search CrossRef by author and/or title."""
    author, title = author.strip(), title.strip()
    if not author and not title:
        raise ValueError("Provide author and/or title")

    params = {"rows": str(rows), "sort": "relevance"}
    if author and title:
        params["query.author"] = author
        params["query.bibliographic"] = title
    elif author:
        params["query.author"] = author
    else:
        params["query.bibliographic"] = title

    data = _get_json("https://api.crossref.org/works?" + urllib.parse.urlencode(params))

    results = []
    for item in data.get("message", {}).get("items", []):
        authors = []
        for a in item.get("author", []):
            name = a.get("family", "")
            if a.get("given"):
                name = a["given"] + " " + name
            authors.append(name)

        title_parts = item.get("title", [])
        year = ""
        for date_field in ("published-print", "published-online", "issued"):
            parts = item.get(date_field, {}).get("date-parts", [[]])
            if parts and parts[0] and parts[0][0]:
                year = str(parts[0][0])
                break

        journal = ""
        for ct in item.get("container-title", []):
            journal = ct
            break

        results.append({
            "doi": item.get("DOI", ""),
            "title": title_parts[0] if title_parts else "(no title)",
            "authors": authors,
            "year": year,
            "journal": journal,
            "type": item.get("type", ""),
        })
    return results


def openalex_search(author="", title="", rows=10):
    """Search OpenAlex - the fallback when CrossRef comes back empty."""
    author, title = author.strip(), title.strip()
    if not author and not title:
        raise ValueError("Provide author or title")

    if author and not title:
        params = {
            "filter": "authorships.author.display_name.search:" + author,
            "per_page": str(rows),
            "mailto": MAILTO,
        }
    else:
        search_parts = [p for p in (title, author) if p]
        params = {
            "search": " ".join(search_parts),
            "per_page": str(rows),
            "mailto": MAILTO,
        }

    data = _get_json("https://api.openalex.org/works?" + urllib.parse.urlencode(params))

    results = []
    for item in data.get("results", []):
        authors = [a.get("author", {}).get("display_name", "")
                   for a in item.get("authorships", [])]
        loc = item.get("primary_location", {}) or {}
        src = loc.get("source", {}) or {}
        results.append({
            "doi": (item.get("doi") or "").replace("https://doi.org/", ""),
            "title": item.get("title") or "(no title)",
            "authors": authors,
            "year": str(item.get("publication_year", "")),
            "journal": src.get("display_name", ""),
            "type": item.get("type", ""),
        })
    return results


def search(author="", title="", rows=10):
    """CrossRef search, falling back to OpenAlex when it finds nothing.

    Returns (results, source).
    """
    try:
        results = crossref_search(author, title, rows)
    except ValueError:
        raise
    except Exception:
        results = []
    if results:
        return results, "crossref"
    return openalex_search(author, title, rows), "openalex"


def bibtex_for_doi(doi):
    """Fetch BibTeX for a DOI from CrossRef, normalized and pretty-printed."""
    url = ("https://api.crossref.org/works/" + urllib.parse.quote(doi, safe="/")
           + "/transform/application/x-bibtex")
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        bibtex = resp.read().decode()
    return format_bibtex(reformat_key(bibtex))


# --- BibTeX manipulation ---

def reformat_key(bibtex):
    """Rewrite cite key from Author_Year to AuthorYear format."""
    authors = re.findall(r'author\s*=\s*\{([^}]+)\}', bibtex, re.IGNORECASE)
    years = re.findall(r'year\s*=\s*\{?(\d{4})\}?', bibtex, re.IGNORECASE)

    if authors and years:
        surnames = []
        for part in re.split(r'\s+and\s+', authors[0]):
            part = part.strip()
            if ',' in part:
                surnames.append(part.split(',')[0].strip())
            else:
                words = part.split()
                if words:
                    surnames.append(words[-1].strip())
        clean = [re.sub(r'[^A-Za-z]', '', s).capitalize() for s in surnames]
        new_key = ''.join(clean) + years[0]
        bibtex = re.sub(r'(@\w+\s*\{)\s*[^,]+,', r'\g<1>' + new_key + ',', bibtex, count=1)

    return bibtex


def format_bibtex(bibtex):
    """Pretty-print BibTeX with consistent indentation and field ordering."""
    # CrossRef returns entries with a leading space; re.match would miss it.
    bibtex = bibtex.strip()
    m = re.match(r'(@\w+)\s*\{\s*([^,]+),\s*', bibtex)
    if not m:
        return bibtex
    entry_type = m.group(1).lower()
    key = m.group(2).strip()

    fields = {}
    for fm in re.finditer(r'(\w+)\s*=\s*', bibtex[m.end():]):
        fname = fm.group(1).lower()
        rest = bibtex[m.end() + fm.end():]
        val = ""
        if rest.startswith('{'):
            depth = 0
            for i, c in enumerate(rest):
                if c == '{':
                    depth += 1
                elif c == '}':
                    depth -= 1
                    if depth == 0:
                        val = rest[1:i]
                        break
        else:
            em = re.match(r'([^,}\s]+)', rest)
            if em:
                val = em.group(1)
        if val or fname not in fields:
            fields[fname] = val

    lines = [f"{entry_type}{{{key},"]
    seen = set()
    for f in BIBTEX_FIELD_ORDER:
        if f in fields:
            lines.append(f"  {f} = {{{fields[f]}}},")
            seen.add(f)
    for f in sorted(fields):
        if f not in seen:
            lines.append(f"  {f} = {{{fields[f]}}},")
    lines.append("}")
    return "\n".join(lines)


def extract_keys_and_dois(text):
    """Extract all cite keys and DOIs from a .bib file's text."""
    keys = set(re.findall(r'@\w+\s*\{\s*([^,]+),', text))
    dois = set()
    for m in re.finditer(r'doi\s*=\s*\{([^}]+)\}', text, re.IGNORECASE):
        dois.add(m.group(1).strip().lower())
    return keys, dois


def get_key(bibtex):
    """Extract the cite key from a BibTeX entry."""
    m = re.match(r'@\w+\s*\{\s*([^,]+),', bibtex)
    return m.group(1).strip() if m else ""


def get_doi(bibtex):
    """Extract the DOI from a BibTeX entry."""
    m = re.search(r'doi\s*=\s*\{([^}]+)\}', bibtex, re.IGNORECASE)
    return m.group(1).strip().lower() if m else ""


def set_key(bibtex, new_key):
    """Replace the cite key in a BibTeX entry."""
    return re.sub(r'(@\w+\s*\{)\s*[^,]+,', r'\g<1>' + new_key + ',', bibtex, count=1)


def deduplicate_key(key, existing_keys):
    """Add a/b/c suffix if key already exists. E.g. BarthKahn2025 -> BarthKahn2025b."""
    if key not in existing_keys:
        return key
    base = re.sub(r'[a-z]$', '', key)
    for suffix in 'bcdefghijklmnopqrstuvwxyz':
        candidate = base + suffix
        if candidate not in existing_keys:
            return candidate
    return key + '_2'


# --- .bib file operations ---

def add_to_bib(bib_path, bibtex):
    """Append an entry to a .bib file, deduplicating keys.

    Raises DuplicateEntry if the DOI is already present. Returns the cite key
    actually written (which may carry a disambiguating suffix).
    """
    fpath = Path(bib_path)
    bibtex = bibtex.strip()
    fpath.parent.mkdir(parents=True, exist_ok=True)

    existing = fpath.read_text() if fpath.exists() else ""

    if existing.strip():
        existing_keys, existing_dois = extract_keys_and_dois(existing)
        new_doi = get_doi(bibtex)
        if new_doi and new_doi in existing_dois:
            raise DuplicateEntry(f"Duplicate: DOI '{new_doi}' already exists")

        new_key = get_key(bibtex)
        if new_key and new_key in existing_keys:
            bibtex = set_key(bibtex, deduplicate_key(new_key, existing_keys))

    if existing.strip():
        fpath.write_text(existing.rstrip("\n") + "\n\n" + bibtex + "\n")
    else:
        fpath.write_text(bibtex + "\n")
    return get_key(bibtex)


def _entry_bounds(text, match):
    """Return (start, end) of the entry block whose header `match` starts."""
    start = match.start()
    depth = 0
    for i in range(match.end(), len(text)):
        if text[i] == '{':
            depth += 1
        elif text[i] == '}':
            if depth == 0:
                return start, i + 1
            depth -= 1
    return start, len(text)


def list_bib(bib_path):
    """List entries in a .bib file as dicts of key/type/title/author/year."""
    fpath = Path(bib_path)
    if not fpath.exists():
        return []

    text = fpath.read_text()
    entries = []
    for m in re.finditer(r'(@\w+)\s*\{\s*([^,]+),', text):
        start, end = _entry_bounds(text, m)
        block = text[start:end]
        title_m = re.search(r'title\s*=\s*\{([^}]+)\}', block, re.IGNORECASE)
        author_m = re.search(r'author\s*=\s*\{([^}]+)\}', block, re.IGNORECASE)
        year_m = re.search(r'year\s*=\s*\{?(\d{4})\}?', block, re.IGNORECASE)
        entries.append({
            "key": m.group(2).strip(),
            "type": m.group(1),
            "title": title_m.group(1) if title_m else "",
            "author": author_m.group(1) if author_m else "",
            "year": year_m.group(1) if year_m else "",
        })
    return entries


def key_for_doi(bib_path, doi):
    """Cite key of the entry with this DOI, or "" if it isn't there."""
    fpath = Path(bib_path)
    if not fpath.exists() or not doi:
        return ""
    doi = doi.strip().lower()
    text = fpath.read_text()
    for m in re.finditer(r'@\w+\s*\{\s*([^,]+),', text):
        start, end = _entry_bounds(text, m)
        if get_doi(text[start:end]) == doi:
            return m.group(1).strip()
    return ""


def delete_entry(bib_path, key):
    """Delete an entry by cite key. Returns True if something was removed."""
    fpath = Path(bib_path)
    if not fpath.exists():
        return False

    text = fpath.read_text()
    m = re.search(r'\n*@\w+\s*\{\s*' + re.escape(key) + r'\s*,', text)
    if not m:
        return False

    depth = 0
    start, end = m.start(), m.start()
    found_open = False
    for i in range(m.start(), len(text)):
        if text[i] == '{':
            depth += 1
            found_open = True
        elif text[i] == '}':
            depth -= 1
            if found_open and depth == 0:
                end = i + 1
                break

    new_text = text[:start] + text[end:]
    new_text = re.sub(r'\n{3,}', '\n\n', new_text).strip() + "\n" if new_text.strip() else ""
    fpath.write_text(new_text)
    return True


def find_bib_paths(doc_path):
    """Find .bib files a LaTeX document refers to.

    Reads \\bibliography{} and \\addbibresource{} from the document, falling
    back to any .bib sitting next to it.
    """
    doc = Path(doc_path)
    found = []
    if doc.exists() and doc.suffix.lower() in (".tex", ".md", ".markdown"):
        try:
            text = doc.read_text(errors="replace")
        except OSError:
            text = ""
        refs = []
        for m in re.finditer(r'\\bibliography\s*\{([^}]+)\}', text):
            refs += [r.strip() for r in m.group(1).split(",")]
        for m in re.finditer(r'\\addbibresource\s*\{([^}]+)\}', text):
            refs.append(m.group(1).strip())
        for ref in refs:
            if not ref:
                continue
            cand = (doc.parent / ref)
            if cand.suffix.lower() != ".bib":
                cand = cand.with_suffix(".bib")
            if cand.exists() and cand not in found:
                found.append(cand)

    if not found and doc.parent.is_dir():
        for cand in sorted(doc.parent.glob("*.bib")):
            found.append(cand)
    return found
