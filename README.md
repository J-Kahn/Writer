# Writer

A distraction-free writing environment for Vim with AI-powered suggestions. Writer provides a clean interface with side panels for document outline, writing suggestions, and critical review.

## Features

- **AI Writing Suggestions**: Get alternative phrasings for existing paragraphs or generate the next paragraph
- **Section Fill**: Automatically generate content for empty sections based on your document outline
- **Document Review**: Get critical feedback on your writing from an AI editor
- **Live Outline**: See your document structure updated in real-time
- **Multiple AI Providers**: Supports both OpenAI (GPT-4, GPT-4o, etc.) and Anthropic (Claude) models
- **Writing Style Customization**: Define your preferred writing style in the config

## Installation

1. Clone this repository
2. Run the setup script:
   ```bash
   ./setup.sh
   ```
3. Copy the example config and add your API key:
   ```bash
   cp config/writer.conf.example ~/.writer/config/writer.conf
   # Edit ~/.writer/config/writer.conf with your API key
   ```

## Usage

Launch Writer with a markdown file:
```bash
./writer document.md
```

### Keybindings

| Key | Action |
|-----|--------|
| `<Leader>ws` | Request writing suggestions |
| `<Leader>w1/w2/w3` | Insert suggestion 1, 2, or 3 |
| `<Leader>wn/wp` | Cycle through suggestion previews |
| `<Leader>wa` | Accept current preview |
| `<Leader>wc` | Clear preview |
| `<Leader>wf` | Fill current section with AI-generated content |
| `<Leader>wr` | Request document review |
| `<Leader>wb` | Search for a citation and insert `\cite{}` |
| `<Leader>wo` | Refresh outline |
| `<Leader>wt` | Toggle Writer on/off |

### Commands

- `:WriterModel <model>` - Switch OpenAI model (e.g., `:WriterModel gpt-4o`)
- `:WriterModelShow` - Show current model
- `:WriterSuggest` - Request suggestions
- `:WriterFill` - Fill current section
- `:WriterReview` - Request document review
- `:WriterCite <query>` - Search CrossRef, pick a result, add it to the `.bib` and insert `\cite{}`
- `:WriterCiteDoi <doi>` - Skip the search and add a known DOI
- `:WriterBib` - Show which `.bib` the current document is wired to

## Configuration

Edit `~/.writer/config/writer.conf`:

```ini
[ai]
# AI provider: "openai" or "claude"
provider = openai

# API keys
openai_api_key = sk-...
anthropic_api_key = sk-ant-...

# Models
openai_model = gpt-4o
claude_model = claude-sonnet-4-20250514

[display]
# Number of suggestions to show (1-5)
suggestion_count = 3

[editor]
# Context window for suggestions
context_lines_before = 50
context_lines_after = 10

# Custom writing style prompt
writing_style = Write in a conversational but professional tone. Use short sentences and active voice.
```

## Citations

Both the web UI and vim share one implementation (`python/citations.py`): CrossRef
lookup with an OpenAlex fallback, DOI to BibTeX, cite keys normalized to
`AuthorYear`, fields ordered consistently, and duplicate detection on both key
and DOI.

In vim:

```
:WriterCite dealer balance sheets repo
```

pick a numbered result, and Writer fetches the BibTeX, appends it to your
bibliography, and inserts `\cite{Key}` at the cursor. If the cursor is already
inside a `\cite{...}`, the key joins that group instead of starting a new one.
An entry you already have doesn't get added twice - you just get its existing key.

`<Leader>wb` is the same thing with a prompt.

### Completing cite keys

`\cite{` completes from your local `.bib` via omni-completion - press
`<C-x><C-o>` inside the braces. It matches on key, author, or title, shows year
and author in the menu and the title in the preview, and never touches the
network. Results are cached until the `.bib` changes on disk.

Set on `tex`, `plaintex`, `markdown`, and `pandoc` buffers, and only if you
haven't already set your own `omnifunc`.

### Which .bib

Writer looks for `\bibliography{...}` or `\addbibresource{...}` in the document,
then falls back to any `.bib` sitting beside it. To pin it explicitly:

```vim
let g:writer_bib_file = '~/Projects/SRP/WR/srp.bib'
```

The same lookup is available from the shell, which is also how the plugin calls it:

```bash
python3 python/cite_cli.py search --author Poole --title "monetary policy"
python3 python/cite_cli.py cite --doi 10.2307/1883009 --doc paper.tex
python3 python/cite_cli.py keys --bib refs.bib
```

## Working on an existing git repository

Writer can pull a whole repository into the writing environment and work on it
in place, rather than copying files around.

### Cloning from GitHub (remote server)

When the Writer server runs on another machine, it clones the repo itself.
In the file browser, the **Repositories** box takes a clone URL:

1. Paste `git@github.com:you/repo.git` and hit **Check** - the server contacts
   the remote, confirms its credentials work, and fills in the branch list.
2. Optionally pick a branch and tick **shallow** (`--depth 1`; worth it when the
   history is large - it only affects what gets downloaded).
3. Hit **Add**. The repo is cloned into the documents directory and appears as a
   normal folder.

Once cloned, the Git panel handles the rest: branch switcher, **Fetch**,
**Pull**, **Push**, and per-file commits.

The server needs its own credentials for the remote. For an SSH URL, put a
deploy key on the account that runs the service:

```bash
sudo -u writer ssh-keygen -t ed25519 -N "" -f /home/writer/.ssh/id_ed25519
sudo -u writer ssh-keyscan github.com >> /home/writer/.ssh/known_hosts
cat /home/writer/.ssh/id_ed25519.pub   # add to GitHub as a deploy key (write access to push)
```

Git runs non-interactively, so a missing key fails fast with a message saying so
rather than hanging the request.

### Linking a local repo (server on the same machine)

If Writer runs on the same machine as your checkout, a local path works too -
`~/Projects/SRP` in the same box symlinks it in, so edits land directly in the
real working tree. Repos can also be linked at startup from the config:

```ini
[web]
documents_dir = ~/Documents/Writer
repos = ~/Projects/SRP, ~/Projects/Notes
```

### Notes

- Registered repos are remembered in `~/.writer/repos.json`. Removing one from
  Writer only drops the symlink or registration - files are never deleted.
- Saves inside a **linked** repo are not auto-committed, since a real project
  repo shouldn't collect a commit per save. **Cloned** repos keep the usual
  auto-commit-on-save behavior. Either default can be flipped:
  `POST /api/repos/<name>` with `{"auto_commit": false}`.

### Repository API

| Endpoint | Purpose |
|----------|---------|
| `POST /api/git/check-remote` | `{"url": "..."}` - test access, list branches |
| `POST /api/repos/clone` | `{"url", "branch"?, "depth"?, "name"?}` - clone |
| `POST /api/repos/link` | `{"path": "~/Projects/SRP"}` - link a local repo |
| `GET /api/repos` | List registered repos with branch and remote |
| `POST /api/repos/<name>` | `{"auto_commit": false}` - update settings |
| `DELETE /api/repos/<name>` | Unregister (files untouched) |
| `GET /api/git/status?dir=repo` | Branch, ahead/behind, changed files |
| `GET /api/git/branches?dir=repo` | Local and remote branches |
| `POST /api/git/checkout` | `{"dir", "branch", "create"?}` |
| `POST /api/git/fetch` | `{"dir"}` - refresh refs from origin |

## Requirements

- Python 3.8+
- Vim 8+ or Neovim
- tmux
- OpenAI API key and/or Anthropic API key

Python dependencies:
```
openai
anthropic
```

## License

MIT
