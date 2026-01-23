#!/usr/bin/env python3
"""
Review Panel - Bottom-left panel TUI showing AI critique.
Acts as a "prosecuting attorney" finding weaknesses in arguments.
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
from ai_client import create_provider, DocumentReview

WRITER_DIR = Path.home() / ".writer"
CONTEXT_FILE = WRITER_DIR / "context.json"
REQUEST_FILE = WRITER_DIR / "request_review"


class ReviewPanel:
    """TUI panel for AI document review/critique."""

    def __init__(self, filename: str):
        self.filename = filename
        self.console = Console()
        self.config = load_config()
        self.provider = create_provider(self.config)

        # State
        self.review: Optional[DocumentReview] = None
        self.is_loading = False
        self.error_message: Optional[str] = None
        self.running = True
        self.last_review_time = 0

    def _create_display(self) -> Panel:
        """Create the review panel."""
        content = Text()
        provider_name = type(self.provider).__name__.replace("Provider", "")

        # Loading state
        if self.is_loading:
            content.append("⏳ Analyzing...\n\n", style="yellow")
            content.append("Reviewing prose and\n", style="dim")
            content.append("finding weaknesses.\n", style="dim")
            return Panel(
                content,
                title="[bold yellow]Review[/bold yellow]",
                border_style="yellow",
                padding=(0, 1)
            )

        # Error state
        if self.error_message:
            content.append("❌ Error\n\n", style="red bold")
            content.append(f"{self.error_message}\n\n", style="red")
            content.append("Try again with ", style="dim")
            content.append("<Leader>wr\n", style="cyan")
            return Panel(
                content,
                title="[bold red]Review[/bold red]",
                border_style="red",
                padding=(0, 1)
            )

        # No review yet
        if self.review is None:
            content.append(f"Provider: {provider_name}\n\n", style="dim")
            content.append("Press ", style="dim")
            content.append("<Leader>wr", style="cyan bold")
            content.append(" to\n", style="dim")
            content.append("review your prose.\n\n", style="dim")
            content.append("The AI will:\n", style="dim")
            content.append("• Score readability\n", style="dim")
            content.append("• Find weak points\n", style="dim")
            content.append("• Suggest fixes\n", style="dim")
            return Panel(
                content,
                title="[bold magenta]Review[/bold magenta]",
                border_style="magenta",
                padding=(0, 1)
            )

        # Display review - one sentence each

        if self.review.critique:
            content.append("Critique\n", style="bold cyan")
            content.append(f"{self.review.critique}\n\n", style="white")

        if self.review.weaknesses:
            content.append("⚠ Weakness\n", style="bold red")
            content.append(f"{self.review.weaknesses}\n\n", style="yellow")

        if self.review.strengths:
            content.append("✓ Strength\n", style="bold green")
            content.append(f"{self.review.strengths}\n", style="green")

        # Footer
        content.append("\n")
        content.append("─" * 22 + "\n", style="dim")
        content.append("<Leader>wr ", style="cyan")
        content.append("refresh\n", style="dim")

        return Panel(
            content,
            title="[bold magenta]Review[/bold magenta]",
            border_style="magenta",
            padding=(0, 1)
        )

    def _generate_review(self):
        """Generate document review."""
        self.is_loading = True
        self.error_message = None

        try:
            # Read context
            if not CONTEXT_FILE.exists():
                self.error_message = "No document context"
                self.is_loading = False
                return

            data = json.loads(CONTEXT_FILE.read_text())
            lines = data.get('lines', [])
            document = '\n'.join(lines)

            if not document.strip():
                self.error_message = "Document is empty"
                self.is_loading = False
                return

            # Generate review
            self.review = self.provider.review_document(document)
            self.last_review_time = time.time()

            # Save review to file for potential vim use
            review_file = WRITER_DIR / "review_result.json"
            review_data = {
                "critique": self.review.critique,
                "weaknesses": self.review.weaknesses,
                "strengths": self.review.strengths,
                "timestamp": self.last_review_time
            }
            review_file.write_text(json.dumps(review_data, indent=2))

        except Exception as e:
            self.error_message = str(e)[:100]
        finally:
            self.is_loading = False

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
                    # Check for review request
                    if REQUEST_FILE.exists():
                        try:
                            REQUEST_FILE.unlink()
                        except Exception:
                            pass
                        thread = threading.Thread(target=self._generate_review, daemon=True)
                        thread.start()

                    live.update(self._create_display())
                    time.sleep(0.25)
        finally:
            self.console.show_cursor(True)


def main():
    if len(sys.argv) < 2:
        print("Usage: review_panel.py <filename>")
        sys.exit(1)

    os.system('clear')
    panel = ReviewPanel(sys.argv[1])
    panel.run()


if __name__ == "__main__":
    main()
