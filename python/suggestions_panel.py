#!/usr/bin/env python3
"""
Suggestions Panel - Right panel TUI showing AI writing suggestions.
Uses rich library for clean display with bordered panel.
"""

import sys
import json
import time
import signal
import os
import threading
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from rich.live import Live

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from config import load_config
from ai_client import create_provider, WritingContext, Suggestion, extract_paragraphs

WRITER_DIR = Path.home() / ".writer"
CONTEXT_FILE = WRITER_DIR / "context.json"
REQUEST_FILE = WRITER_DIR / "request_suggestions"
FILL_REQUEST_FILE = WRITER_DIR / "request_fill_section"


class SuggestionsPanel:
    """TUI panel for AI writing suggestions."""

    def __init__(self, filename: str):
        self.filename = filename
        self.console = Console()
        self.config = load_config()
        self.provider = create_provider(self.config)

        # State
        self.suggestions: list[Suggestion] = []
        self.is_loading = False
        self.error_message: Optional[str] = None
        self.current_paragraph_preview: str = ""
        self.preview_index: int = 0  # Currently previewed suggestion
        self.running = True
        self.mode: str = "alternatives"  # "alternatives" or "next_paragraph"

    def _create_display(self) -> Panel:
        """Create the suggestions panel."""
        content = Text()
        provider_name = type(self.provider).__name__.replace("Provider", "")

        # Loading state
        if self.is_loading:
            content.append("⏳ Generating...\n\n", style="yellow")
            content.append("Analyzing paragraph and\n", style="dim")
            content.append("generating continuations.\n", style="dim")
            return Panel(
                content,
                title="[bold yellow]Suggestions[/bold yellow]",
                border_style="yellow",
                padding=(0, 1)
            )

        # Error state
        if self.error_message:
            content.append("❌ Error\n\n", style="red bold")
            content.append(f"{self.error_message}\n\n", style="red")
            content.append("Try again with ", style="dim")
            content.append("<Leader>ws\n", style="cyan")
            return Panel(
                content,
                title="[bold red]Suggestions[/bold red]",
                border_style="red",
                padding=(0, 1)
            )

        # No suggestions yet
        if not self.suggestions:
            content.append(f"Provider: {provider_name}\n\n", style="dim")
            content.append("Press ", style="dim")
            content.append("<Leader>ws", style="cyan bold")
            content.append(":\n", style="dim")
            content.append("• On text → alternatives\n", style="dim")
            content.append("• On empty → next para\n\n", style="dim")
            content.append("─" * 25 + "\n", style="dim")
            content.append("<Leader>wf ", style="cyan")
            content.append("fill section\n", style="dim")
            return Panel(
                content,
                title="[bold cyan]Suggestions[/bold cyan]",
                border_style="blue",
                padding=(0, 1)
            )

        # Mode indicator
        if self.mode == "alternatives":
            content.append("✎ Alternatives\n", style="bold magenta")
            content.append("(replaces paragraph)\n\n", style="dim")
        else:
            content.append("✚ Next Paragraph\n", style="bold cyan")
            content.append("(inserts new)\n\n", style="dim")

        # Current paragraph context
        if self.current_paragraph_preview and self.mode == "alternatives":
            para_short = self.current_paragraph_preview[:50]
            if len(self.current_paragraph_preview) > 50:
                para_short += "..."
            content.append("Original:\n", style="dim")
            content.append(f'"{para_short}"\n\n', style="italic dim")

        # Display suggestions
        for i, suggestion in enumerate(self.suggestions, 1):
            is_previewing = (i - 1 == self.preview_index)
            if is_previewing:
                content.append(f"▶ [{i}] ", style="bold green")
                content.append("(previewing)\n", style="green dim")
            else:
                content.append(f"  [{i}] ", style="bold cyan")
                content.append("─" * 20 + "\n", style="dim")

            # Preview (truncated)
            preview = suggestion.text[:120]
            if len(suggestion.text) > 120:
                preview += "..."

            style = "white" if not is_previewing else "green"
            content.append(f"{preview}\n\n", style=style)

        # Footer with keybindings
        content.append("─" * 25 + "\n", style="dim")
        content.append("<Leader>wn/wp ", style="cyan")
        content.append("cycle\n", style="dim")
        content.append("<Leader>wa ", style="cyan")
        content.append("accept preview\n", style="dim")
        content.append("<Leader>wc ", style="cyan")
        content.append("clear preview\n", style="dim")

        return Panel(
            content,
            title="[bold green]Suggestions[/bold green]",
            border_style="green",
            padding=(0, 1)
        )

    def _generate_suggestions(self):
        """Generate suggestions - alternatives or next paragraph based on context."""
        self.is_loading = True
        self.error_message = None
        self.suggestions = []
        self.preview_index = 0

        try:
            # Read context
            if not CONTEXT_FILE.exists():
                self.error_message = "No context available"
                self.is_loading = False
                return

            data = json.loads(CONTEXT_FILE.read_text())
            lines = data.get('lines', [])
            cursor_line = data.get('cursor_line', 1)
            current_line_text = data.get('current', '')

            # Determine mode based on whether current line is empty
            is_empty = not current_line_text.strip()

            # Extract paragraph context
            para_before, current_para, para_after = extract_paragraphs(lines, cursor_line)

            # Set mode
            if is_empty or not current_para.strip():
                self.mode = "next_paragraph"
                self.current_paragraph_preview = para_before
            else:
                self.mode = "alternatives"
                self.current_paragraph_preview = current_para

            # Build context
            context = WritingContext(
                full_document='\n'.join(lines),
                current_paragraph=current_para,
                paragraph_before=para_before,
                paragraph_after=para_after,
                cursor_line=cursor_line,
                filename=data.get('filename', self.filename),
                document_type='markdown',
                is_empty_line=is_empty
            )

            # Generate
            self.suggestions = self.provider.generate_suggestions(
                context,
                count=self.config.display.suggestion_count
            )

            # Save to files for vim to read
            for i, s in enumerate(self.suggestions, 1):
                suggestion_file = WRITER_DIR / f"suggestion_{i}.txt"
                suggestion_file.write_text(s.text)

            # Write preview state
            self._write_preview_state()

        except Exception as e:
            self.error_message = str(e)[:100]
        finally:
            self.is_loading = False

    def _fill_section(self):
        """Generate content for a section from outline."""
        self.is_loading = True
        self.error_message = None

        try:
            # Read fill request
            if not FILL_REQUEST_FILE.exists():
                self.is_loading = False
                return

            request_data = json.loads(FILL_REQUEST_FILE.read_text())
            FILL_REQUEST_FILE.unlink()

            section_heading = request_data.get('heading', '')
            outline = request_data.get('outline', [])

            if not section_heading:
                self.error_message = "No section heading provided"
                self.is_loading = False
                return

            # Read current document
            if CONTEXT_FILE.exists():
                data = json.loads(CONTEXT_FILE.read_text())
                document = '\n'.join(data.get('lines', []))
            else:
                document = ""

            # Generate section content
            result = self.provider.fill_section(document, section_heading, outline)

            # Save result
            fill_result_file = WRITER_DIR / "fill_result.txt"
            fill_result_file.write_text(result.content)

            # Show in suggestions
            self.suggestions = [
                Suggestion(
                    text=result.content,
                    confidence=0.9,
                    description=f"Content for: {section_heading}"
                )
            ]
            self.current_paragraph_preview = f"Section: {section_heading}"

            # Save as suggestion 1
            suggestion_file = WRITER_DIR / "suggestion_1.txt"
            suggestion_file.write_text(result.content)

        except Exception as e:
            self.error_message = str(e)[:100]
        finally:
            self.is_loading = False

    def _write_preview_state(self):
        """Write current preview state for vim."""
        preview_file = WRITER_DIR / "preview_state.json"
        state = {
            "index": self.preview_index,
            "count": len(self.suggestions),
            "text": self.suggestions[self.preview_index].text if self.suggestions else "",
            "mode": self.mode  # "alternatives" or "next_paragraph"
        }
        preview_file.write_text(json.dumps(state))

        # Also write mode to separate file for vim
        mode_file = WRITER_DIR / "suggestion_mode.txt"
        mode_file.write_text(self.mode)

    def _check_preview_commands(self):
        """Check for preview navigation commands."""
        next_file = WRITER_DIR / "preview_next"
        prev_file = WRITER_DIR / "preview_prev"

        if next_file.exists():
            next_file.unlink()
            if self.suggestions:
                self.preview_index = (self.preview_index + 1) % len(self.suggestions)
                self._write_preview_state()

        if prev_file.exists():
            prev_file.unlink()
            if self.suggestions:
                self.preview_index = (self.preview_index - 1) % len(self.suggestions)
                self._write_preview_state()

    def run(self):
        """Run the panel."""
        signal.signal(signal.SIGINT, lambda s, f: setattr(self, 'running', False))
        signal.signal(signal.SIGTERM, lambda s, f: setattr(self, 'running', False))

        self.console.show_cursor(False)

        try:
            with Live(
                self._create_display(),
                console=self.console,
                refresh_per_second=4,
                screen=True
            ) as live:
                while self.running:
                    # Check for suggestion request
                    if REQUEST_FILE.exists():
                        try:
                            REQUEST_FILE.unlink()
                        except Exception:
                            pass
                        thread = threading.Thread(target=self._generate_suggestions, daemon=True)
                        thread.start()

                    # Check for fill section request
                    if FILL_REQUEST_FILE.exists():
                        thread = threading.Thread(target=self._fill_section, daemon=True)
                        thread.start()

                    # Check for preview navigation
                    self._check_preview_commands()

                    live.update(self._create_display())
                    time.sleep(0.25)
        finally:
            self.console.show_cursor(True)


def main():
    if len(sys.argv) < 2:
        print("Usage: suggestions_panel.py <filename>")
        sys.exit(1)

    os.system('clear')
    panel = SuggestionsPanel(sys.argv[1])
    panel.run()


if __name__ == "__main__":
    main()
