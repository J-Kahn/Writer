#!/bin/bash
# Writer - Vim-Based Terminal Writing Environment Setup Script

set -e

WRITER_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_DIR="$HOME/.writer"
FIFO_DIR="$CONFIG_DIR/fifo"

echo "Setting up Writer..."

# Create config directory structure
mkdir -p "$CONFIG_DIR/config"
mkdir -p "$FIFO_DIR"

# Copy example config if no config exists
if [ ! -f "$CONFIG_DIR/config/writer.conf" ]; then
    cp "$WRITER_DIR/config/writer.conf.example" "$CONFIG_DIR/config/writer.conf"
    echo "Created config file at $CONFIG_DIR/config/writer.conf"
    echo "Please edit this file to add your API keys."
fi

# Create named pipes (FIFOs)
for fifo in vim_to_outline vim_to_suggestions outline_to_vim suggestions_to_vim; do
    fifo_path="$FIFO_DIR/$fifo"
    if [ ! -p "$fifo_path" ]; then
        mkfifo "$fifo_path"
        echo "Created FIFO: $fifo_path"
    fi
done

# Make writer script executable
chmod +x "$WRITER_DIR/writer"

# Install Python dependencies
echo "Installing Python dependencies..."
pip install --user openai anthropic rich 2>/dev/null || {
    echo "Note: Could not install Python packages with pip."
    echo "Please install manually: pip install openai anthropic rich"
}

# Symlink vim plugin (optional)
VIM_PLUGIN_DIR="$HOME/.vim/plugin"
if [ -d "$HOME/.vim" ]; then
    mkdir -p "$VIM_PLUGIN_DIR"
    if [ ! -L "$VIM_PLUGIN_DIR/writer.vim" ]; then
        ln -sf "$WRITER_DIR/vim/plugin/writer.vim" "$VIM_PLUGIN_DIR/writer.vim"
        echo "Linked vim plugin to $VIM_PLUGIN_DIR/writer.vim"
    fi
fi

echo ""
echo "Setup complete!"
echo ""
echo "Next steps:"
echo "  1. Edit ~/.writer/config/writer.conf to add your API keys"
echo "  2. Run: ./writer <filename.md> to start writing"
echo ""
echo "Keybindings:"
echo "  Ctrl+h/j/k/l  - Navigate between tmux panes"
echo "  <Leader>ws    - Request AI writing suggestions"
echo "  <Leader>wo    - Force outline refresh"
echo "  <Leader>w1/2/3 - Insert suggestion 1, 2, or 3"
