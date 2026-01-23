#!/usr/bin/env python3
"""
Outline Panel - Left panel TUI showing document structure.
Uses rich library for clean display with bordered panel.
Shows empty sections that can be filled with AI.
"""

import sys
import json
import time
import signal
import os
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from rich.live import Live

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from document_parser import parse_markdown, DocumentOutline, OutlineItem, get_current_section
from config import load_config

WRITER_DIR = Path.home() / ".writer"
CONTEXT_FILE = WRITER_DIR / "context.json"
REQUEST_FILE = WRITER_DIR / "request_outline"


class OutlinePanel:
    """TUI panel for document outline display."""

    def __init__(self, filename: str):
        self.filename = filename
        self.console = Console()
        self.config = load_config()

        # State
        self.outline: Optional[DocumentOutline] = None
        self.cursor_line: int = 1
        self.lines: list[str] = []
        self.running = True
        self.last_context_mtime = 0

        # Load initial content
        self._load_initial()

    def _load_initial(self):
        """Load initial content from file."""
        try:
            filepath = Path(self.filename)
            if filepath.exists():
                content = filepath.read_text()
                self.lines = content.split('\n')
                self.outline = parse_markdown(content)
        except Exception:
            pass

    def _read_context(self):
        """Read context from vim if available."""
        try:
            if CONTEXT_FILE.exists():
                mtime = CONTEXT_FILE.stat().st_mtime
                if mtime > self.last_context_mtime:
                    self.last_context_mtime = mtime
                    data = json.loads(CONTEXT_FILE.read_text())
                    self.lines = data.get('lines', [])
                    self.cursor_line = data.get('cursor_line', 1)
                    self.outline = parse_markdown(self.lines)
        except Exception:
            pass

    def _is_section_empty(self, item: OutlineItem) -> bool:
        """Check if a section has no content (only whitespace until next heading)."""
        if item.item_type != "heading":
            return False

        start_line = item.line_number
        # Find content between this heading and next heading or end
        for i in range(start_line, len(self.lines)):
            line = self.lines[i]
            # Skip the heading itself
            if i == start_line - 1:
                continue
            # Check for next heading
            if line.strip().startswith('#'):
                break
            # Check for non-empty content
            if line.strip():
                return False
        return True

    def _create_display(self) -> Panel:
        """Create the outline panel."""
        content = Text()

        if self.outline is None:
            content.append("Loading...\n", style="dim italic")
            return Panel(
                content,
                title="[bold cyan]Outline[/bold cyan]",
                border_style="blue",
                padding=(0, 1)
            )

        # Title and stats
        if self.outline.title:
            content.append(f"{self.outline.title}\n", style="bold")
        else:
            content.append(f"{Path(self.filename).name}\n", style="bold")

        content.append(f"{self.outline.word_count} words", style="dim")
        content.append(" · ", style="dim")
        content.append(f"{self.outline.line_count} lines\n\n", style="dim")

        # Current section
        current = get_current_section(self.outline, self.cursor_line)

        # Count empty sections
        empty_count = sum(1 for item in self.outline.items
                        if item.item_type == "heading" and self._is_section_empty(item))

        # Headings
        if not self.outline.items:
            content.append("(no headings)\n\n", style="dim italic")
            content.append("Add headings with # syntax\n", style="dim")
            content.append("then use ", style="dim")
            content.append("<Leader>wf", style="cyan")
            content.append(" to fill\n", style="dim")
        else:
            for item in self.outline.items:
                if item.item_type == "heading":
                    is_empty = self._is_section_empty(item)
                    self._render_heading(content, item, item == current, is_empty)
                elif item.item_type == "code":
                    content.append(f"    {item.text}\n", style="dim cyan")

        # Empty sections indicator
        if empty_count > 0:
            content.append("\n")
            content.append(f"◇ {empty_count} empty section(s)\n", style="yellow")
            content.append("  Use ", style="dim")
            content.append("<Leader>wf", style="cyan")
            content.append(" to fill\n", style="dim")

        # Footer
        content.append("\n")
        content.append("─" * 22 + "\n", style="dim")
        content.append("<Leader>wo ", style="cyan")
        content.append("refresh\n", style="dim")
        content.append("<Leader>wf ", style="cyan")
        content.append("fill section\n", style="dim")

        return Panel(
            content,
            title="[bold cyan]Outline[/bold cyan]",
            border_style="blue",
            padding=(0, 1)
        )

    def _render_heading(self, content: Text, item: OutlineItem, is_current: bool, is_empty: bool):
        """Render a single heading item."""
        indent = "  " * (item.level - 1)

        # Icon for empty sections
        if is_empty:
            empty_marker = "◇"  # Diamond for empty
        else:
            empty_marker = "◆"  # Filled diamond

        if is_current:
            content.append("→ ", style="bold green")
            content.append(indent)
            if is_empty:
                content.append(f"{empty_marker} ", style="yellow")
            else:
                content.append("▸ ", style="bold green")
            content.append(f"{item.text}", style="bold green")
            content.append(f" :{item.line_number}\n", style="dim green")
        else:
            content.append("  ")
            content.append(indent)
            if is_empty:
                content.append(f"{empty_marker} ", style="yellow")
                content.append(f"{item.text}", style="yellow")
            else:
                content.append("• ", style="dim")
                content.append(f"{item.text}")
            content.append(f" :{item.line_number}\n", style="dim")

    def run(self):
        """Run the panel."""
        # Handle signals
        signal.signal(signal.SIGINT, lambda s, f: setattr(self, 'running', False))
        signal.signal(signal.SIGTERM, lambda s, f: setattr(self, 'running', False))

        # Hide cursor
        self.console.show_cursor(False)

        try:
            with Live(
                self._create_display(),
                console=self.console,
                refresh_per_second=2,
                screen=True  # Use alternate screen buffer
            ) as live:
                while self.running:
                    # Check for updates
                    self._read_context()

                    # Check for refresh request
                    if REQUEST_FILE.exists():
                        try:
                            REQUEST_FILE.unlink()
                        except Exception:
                            pass
                        self._load_initial()

                    live.update(self._create_display())
                    time.sleep(0.4)
        finally:
            self.console.show_cursor(True)


def main():
    if len(sys.argv) < 2:
        print("Usage: outline_panel.py <filename>")
        sys.exit(1)

    # Clear screen and hide any shell artifacts
    os.system('clear')

    panel = OutlinePanel(sys.argv[1])
    panel.run()


if __name__ == "__main__":
    main()
