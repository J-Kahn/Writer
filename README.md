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
| `<Leader>wo` | Refresh outline |
| `<Leader>wt` | Toggle Writer on/off |

### Commands

- `:WriterModel <model>` - Switch OpenAI model (e.g., `:WriterModel gpt-4o`)
- `:WriterModelShow` - Show current model
- `:WriterSuggest` - Request suggestions
- `:WriterFill` - Fill current section
- `:WriterReview` - Request document review

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
