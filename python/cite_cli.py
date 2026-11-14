#!/usr/bin/env python3
"""
Command-line front end for citation lookup, used by writer.vim.

Every subcommand prints a single JSON object on stdout. Errors print
{"error": "..."} and exit 1, so vim can json_decode() the output either way.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import citations


def _out(obj, code=0):
    print(json.dumps(obj))
    sys.exit(code)


def _resolve_bib(args):
    """Pick the .bib file to work on: --bib wins, else derive from --doc."""
    if args.bib:
        return Path(args.bib).expanduser()
    if args.doc:
        found = citations.find_bib_paths(Path(args.doc).expanduser())
        if found:
            return found[0]
    return None


def cmd_search(args):
    try:
        results, source = citations.search(args.author, args.title, args.rows)
    except ValueError as e:
        _out({"error": str(e)}, 1)
    except Exception as e:
        _out({"error": f"Lookup failed: {e}"}, 1)
    _out({"results": results, "source": source})


def cmd_bibtex(args):
    try:
        _out({"bibtex": citations.bibtex_for_doi(args.doi)})
    except Exception as e:
        _out({"error": f"Could not fetch BibTeX for {args.doi}: {e}"}, 1)


def cmd_cite(args):
    """Fetch a DOI's BibTeX and append it to the .bib in one step."""
    bib = _resolve_bib(args)
    if bib is None:
        _out({"error": "No .bib file found - pass --bib or add \\bibliography{} to the document"}, 1)

    try:
        bibtex = citations.bibtex_for_doi(args.doi)
    except Exception as e:
        _out({"error": f"Could not fetch BibTeX for {args.doi}: {e}"}, 1)

    try:
        cite_key = citations.add_to_bib(bib, bibtex)
    except citations.DuplicateEntry:
        # Already have this paper - hand back the existing key so vim can still
        # insert the \cite command.
        existing = citations.key_for_doi(bib, citations.get_doi(bibtex))
        if existing:
            _out({"cite_key": existing, "bib": str(bib), "duplicate": True})
        _out({"error": "Duplicate DOI already in bibliography"}, 1)
    except OSError as e:
        _out({"error": f"Could not write {bib}: {e}"}, 1)

    _out({"cite_key": cite_key, "bib": str(bib), "duplicate": False})


def cmd_add(args):
    bib = _resolve_bib(args)
    if bib is None:
        _out({"error": "No .bib file found - pass --bib"}, 1)
    bibtex = sys.stdin.read()
    if not bibtex.strip():
        _out({"error": "No BibTeX on stdin"}, 1)
    try:
        cite_key = citations.add_to_bib(bib, bibtex)
    except citations.DuplicateEntry as e:
        _out({"error": str(e)}, 1)
    _out({"cite_key": cite_key, "bib": str(bib)})


def cmd_keys(args):
    """List entries in the bibliography - drives vim's \\cite{} completion."""
    bib = _resolve_bib(args)
    if bib is None:
        _out({"entries": [], "bib": ""})
    _out({"entries": citations.list_bib(bib), "bib": str(bib)})


def cmd_bibpaths(args):
    paths = citations.find_bib_paths(Path(args.doc).expanduser())
    _out({"paths": [str(p) for p in paths]})


def main():
    parser = argparse.ArgumentParser(description="Writer citation lookup")
    sub = parser.add_subparsers(dest="cmd", required=True)

    def add_bib_args(p):
        p.add_argument("--bib", help="Path to the .bib file")
        p.add_argument("--doc", help="Document to derive the .bib from")

    p = sub.add_parser("search", help="Search CrossRef (OpenAlex fallback)")
    p.add_argument("--author", default="")
    p.add_argument("--title", default="")
    p.add_argument("--rows", type=int, default=10)
    p.set_defaults(func=cmd_search)

    p = sub.add_parser("bibtex", help="Fetch BibTeX for a DOI")
    p.add_argument("--doi", required=True)
    p.set_defaults(func=cmd_bibtex)

    p = sub.add_parser("cite", help="Fetch a DOI and append it to the .bib")
    p.add_argument("--doi", required=True)
    add_bib_args(p)
    p.set_defaults(func=cmd_cite)

    p = sub.add_parser("add", help="Append BibTeX read from stdin")
    add_bib_args(p)
    p.set_defaults(func=cmd_add)

    p = sub.add_parser("keys", help="List cite keys in the bibliography")
    add_bib_args(p)
    p.set_defaults(func=cmd_keys)

    p = sub.add_parser("bibpaths", help="Find .bib files for a document")
    p.add_argument("--doc", required=True)
    p.set_defaults(func=cmd_bibpaths)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
