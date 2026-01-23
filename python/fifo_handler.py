"""
FIFO Handler - Named pipe communication for Writer components.

Provides non-blocking read/write operations for inter-process communication
between vim, outline panel, and suggestions panel.
"""

import os
import select
import threading
import json
from pathlib import Path
from typing import Optional, Callable, Any

FIFO_DIR = Path.home() / ".writer" / "fifo"

# FIFO names
FIFOS = {
    "vim_to_outline": FIFO_DIR / "vim_to_outline",
    "vim_to_suggestions": FIFO_DIR / "vim_to_suggestions",
    "outline_to_vim": FIFO_DIR / "outline_to_vim",
    "suggestions_to_vim": FIFO_DIR / "suggestions_to_vim",
}


def ensure_fifos_exist():
    """Create FIFO directory and pipes if they don't exist."""
    FIFO_DIR.mkdir(parents=True, exist_ok=True)
    for name, path in FIFOS.items():
        if not path.exists():
            os.mkfifo(path)


class FifoReader:
    """Non-blocking FIFO reader with callback support."""

    def __init__(self, fifo_name: str, callback: Callable[[str], None]):
        """
        Initialize a FIFO reader.

        Args:
            fifo_name: Name of the FIFO (key in FIFOS dict)
            callback: Function to call when data is received
        """
        self.fifo_path = FIFOS[fifo_name]
        self.callback = callback
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._fd: Optional[int] = None

    def start(self):
        """Start reading from the FIFO in a background thread."""
        if self._running:
            return

        self._running = True
        self._thread = threading.Thread(target=self._read_loop, daemon=True)
        self._thread.start()

    def stop(self):
        """Stop the reader thread."""
        self._running = False
        if self._fd is not None:
            try:
                os.close(self._fd)
            except OSError:
                pass
            self._fd = None
        if self._thread:
            self._thread.join(timeout=1.0)

    def _read_loop(self):
        """Background thread that reads from FIFO."""
        import time

        while self._running:
            fd = None
            try:
                # Open FIFO in read-only, non-blocking mode
                fd = os.open(str(self.fifo_path), os.O_RDONLY | os.O_NONBLOCK)
                self._fd = fd

                buffer = ""
                while self._running and fd is not None:
                    try:
                        # Use select to wait for data with timeout
                        readable, _, _ = select.select([fd], [], [], 0.5)
                    except (ValueError, OSError):
                        # fd was closed
                        break

                    if readable:
                        try:
                            data = os.read(fd, 4096)
                            if not data:
                                # EOF - writer closed, reopen
                                break

                            buffer += data.decode('utf-8', errors='replace')

                            # Process complete messages (newline-delimited)
                            while '\n' in buffer:
                                line, buffer = buffer.split('\n', 1)
                                if line.strip():
                                    try:
                                        self.callback(line)
                                    except Exception:
                                        pass  # Don't let callback errors kill the reader
                        except OSError:
                            break

            except OSError:
                # FIFO doesn't exist or other error - wait and retry
                time.sleep(0.5)
            finally:
                # Clean up fd
                if fd is not None:
                    try:
                        os.close(fd)
                    except OSError:
                        pass
                self._fd = None

            # Brief pause before reopening
            if self._running:
                time.sleep(0.1)


class FifoWriter:
    """FIFO writer for sending messages."""

    def __init__(self, fifo_name: str):
        """
        Initialize a FIFO writer.

        Args:
            fifo_name: Name of the FIFO (key in FIFOS dict)
        """
        self.fifo_path = FIFOS[fifo_name]
        self._lock = threading.Lock()

    def write(self, message: str):
        """
        Write a message to the FIFO.

        Args:
            message: Message to write (newline will be appended)
        """
        with self._lock:
            try:
                # Open in write mode, non-blocking
                # This will fail if no reader - that's OK
                fd = os.open(str(self.fifo_path), os.O_WRONLY | os.O_NONBLOCK)
                try:
                    data = (message.rstrip('\n') + '\n').encode('utf-8')
                    os.write(fd, data)
                finally:
                    os.close(fd)
            except OSError:
                # No reader connected, silently ignore
                pass

    def write_json(self, data: Any):
        """
        Write JSON-encoded data to the FIFO.

        Args:
            data: Data to JSON-encode and write
        """
        self.write(json.dumps(data))


class MessageProtocol:
    """
    Message protocol for structured communication.

    Messages are JSON objects with a 'type' field and optional 'data' field.
    """

    @staticmethod
    def create(msg_type: str, data: Any = None) -> str:
        """Create a protocol message."""
        msg = {"type": msg_type}
        if data is not None:
            msg["data"] = data
        return json.dumps(msg)

    @staticmethod
    def parse(message: str) -> tuple[str, Any]:
        """
        Parse a protocol message.

        Returns:
            Tuple of (message_type, data)
        """
        try:
            msg = json.loads(message)
            return msg.get("type", "unknown"), msg.get("data")
        except json.JSONDecodeError:
            return "raw", message


# Message types
class MsgTypes:
    # Vim -> Panels
    BUFFER_UPDATE = "buffer_update"  # Full buffer content
    CURSOR_POSITION = "cursor_pos"    # Cursor line/col
    REQUEST_SUGGESTIONS = "req_suggestions"  # User requested suggestions
    REQUEST_OUTLINE = "req_outline"   # User requested outline refresh

    # Panels -> Vim
    JUMP_TO_LINE = "jump_line"        # Jump to specific line
    INSERT_TEXT = "insert_text"       # Insert text at cursor

    # Control
    SHUTDOWN = "shutdown"             # Signal to shut down
