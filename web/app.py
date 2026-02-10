"""
Writer Web - Flask backend for the web-based writing environment.

Serves the SPA and handles WebSocket events for AI panels.
Reuses existing AI client, config, and document parser code.
"""

import sys
import os
import subprocess
from pathlib import Path
from functools import wraps

from flask import Flask, request, jsonify, send_from_directory, Response

# Add python/ to path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "python"))

from config import load_config
from ai_client import create_provider, WritingContext, extract_paragraphs, ChatMessage
from document_parser import parse_markdown, get_current_section

app = Flask(__name__, static_folder="static")
app.config["SECRET_KEY"] = os.urandom(24)

# Will be initialized in create_app()
writer_config = None
ai_provider = None
documents_dir = None


def create_app():
    """Initialize app with config."""
    global writer_config, ai_provider, documents_dir

    writer_config = load_config()
    ai_provider = create_provider(writer_config)
    documents_dir = Path(writer_config.web.documents_dir).expanduser().resolve()
    documents_dir.mkdir(parents=True, exist_ok=True)

    try:
        from flask_socketio import SocketIO
        socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")
        register_socket_events(socketio)
    except ImportError:
        socketio = None
        print("Warning: flask-socketio not installed, WebSocket features disabled")

    return app, socketio


def check_auth(username, password):
    """Check if credentials match config."""
    return (username == writer_config.web.username and
            password == writer_config.web.password)


def requires_auth(f):
    """HTTP Basic Auth decorator."""
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.authorization
        if not auth or not check_auth(auth.username, auth.password):
            return Response(
                "Authentication required.",
                401,
                {"WWW-Authenticate": 'Basic realm="Writer"'}
            )
        return f(*args, **kwargs)
    return decorated


def safe_path(requested_path):
    """Resolve path safely within documents_dir."""
    resolved = (documents_dir / requested_path).resolve()
    if not str(resolved).startswith(str(documents_dir)):
        return None
    return resolved


# --- HTTP Routes ---

@app.route("/")
@requires_auth
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.route("/api/files", methods=["GET"])
@requires_auth
def list_files():
    """List files and directories. Use ?dir=path to browse subdirectories."""
    subdir = request.args.get("dir", "")
    target = safe_path(subdir) if subdir else documents_dir
    if target is None or not target.is_dir():
        return jsonify({"error": "Invalid directory"}), 400

    entries = []
    for p in sorted(target.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
        if p.name.startswith("."):
            continue
        rel = p.relative_to(documents_dir)
        entry = {"path": str(rel), "name": p.name}
        if p.is_dir():
            entry["type"] = "dir"
            entry["is_git"] = (p / ".git").is_dir()
        else:
            entry["type"] = "file"
            entry["size"] = p.stat().st_size
            entry["modified"] = p.stat().st_mtime
        entries.append(entry)

    return jsonify({"dir": subdir, "entries": entries})


@app.route("/api/files/<path:filepath>", methods=["GET"])
@requires_auth
def get_file(filepath):
    """Read a file."""
    fpath = safe_path(filepath)
    if fpath is None:
        return jsonify({"error": "Invalid path"}), 400
    if not fpath.exists():
        return jsonify({"error": "Not found"}), 404
    return jsonify({"path": filepath, "content": fpath.read_text()})


@app.route("/api/files/<path:filepath>", methods=["PUT"])
@requires_auth
def save_file(filepath):
    """Save/create a file, auto-commit if in a git repo."""
    fpath = safe_path(filepath)
    if fpath is None:
        return jsonify({"error": "Invalid path"}), 400
    fpath.parent.mkdir(parents=True, exist_ok=True)
    data = request.get_json()
    content = data.get("content", "")
    fpath.write_text(content)

    # Auto-commit if file is inside a git repo
    git_root = _find_git_root(fpath)
    if git_root:
        _git_auto_commit(git_root, fpath)

    return jsonify({"status": "ok", "path": filepath})


@app.route("/api/files/<path:filepath>", methods=["DELETE"])
@requires_auth
def delete_file(filepath):
    """Delete a file."""
    fpath = safe_path(filepath)
    if fpath is None:
        return jsonify({"error": "Invalid path"}), 400
    if not fpath.exists():
        return jsonify({"error": "Not found"}), 404
    fpath.unlink()
    return jsonify({"status": "ok"})


# --- Git helpers ---

def _find_git_root(fpath):
    """Find the git root for a file, or None if not in a repo."""
    d = fpath if fpath.is_dir() else fpath.parent
    while d != d.parent:
        if (d / ".git").is_dir():
            return d
        # Don't look above documents_dir
        if d == documents_dir:
            return None
        d = d.parent
    return None


def _git_run(git_root, *args):
    """Run a git command and return (success, stdout)."""
    try:
        result = subprocess.run(
            ["git"] + list(args),
            cwd=str(git_root),
            capture_output=True, text=True, timeout=10,
        )
        return result.returncode == 0, result.stdout.strip()
    except Exception as e:
        return False, str(e)


def _git_auto_commit(git_root, fpath):
    """Stage and auto-commit a file (silent, best-effort)."""
    rel = fpath.relative_to(git_root)
    _git_run(git_root, "add", str(rel))
    # Only commit if there are staged changes
    ok, status = _git_run(git_root, "diff", "--cached", "--quiet")
    if not ok:  # exit code 1 means there are staged changes
        _git_run(git_root, "commit", "-m", f"Auto-save: {rel.name}")


def _git_init(dirpath):
    """Initialize a git repo in the given directory."""
    return _git_run(dirpath, "init")


# --- Git API routes ---

@app.route("/api/git/commit", methods=["POST"])
@requires_auth
def git_commit():
    """Manual commit with a custom message."""
    data = request.get_json()
    filepath = data.get("path", "")
    message = data.get("message", "").strip()
    if not filepath or not message:
        return jsonify({"error": "Path and message required"}), 400

    fpath = safe_path(filepath)
    if fpath is None or not fpath.exists():
        return jsonify({"error": "Invalid file"}), 400

    git_root = _find_git_root(fpath)
    if not git_root:
        return jsonify({"error": "File is not in a git repository"}), 400

    rel = fpath.relative_to(git_root)
    _git_run(git_root, "add", str(rel))
    ok, out = _git_run(git_root, "commit", "-m", message)
    if ok:
        return jsonify({"status": "ok", "message": out})
    else:
        return jsonify({"error": out or "Nothing to commit"}), 400


@app.route("/api/git/log/<path:filepath>", methods=["GET"])
@requires_auth
def git_log(filepath):
    """Get recent git log for a file."""
    fpath = safe_path(filepath)
    if fpath is None:
        return jsonify({"error": "Invalid path"}), 400

    git_root = _find_git_root(fpath)
    if not git_root:
        return jsonify({"entries": [], "is_repo": False})

    rel = fpath.relative_to(git_root)
    ok, out = _git_run(
        git_root, "log", "--oneline", "--format=%h|%s|%ar", "-n", "20", "--", str(rel)
    )
    entries = []
    if ok and out:
        for line in out.split("\n"):
            parts = line.split("|", 2)
            if len(parts) == 3:
                entries.append({"hash": parts[0], "message": parts[1], "when": parts[2]})

    return jsonify({"entries": entries, "is_repo": True})


@app.route("/api/git/init", methods=["POST"])
@requires_auth
def git_init():
    """Initialize a git repo in a directory."""
    data = request.get_json()
    dirpath = data.get("dir", "")
    target = safe_path(dirpath) if dirpath else documents_dir
    if target is None or not target.is_dir():
        return jsonify({"error": "Invalid directory"}), 400

    if (target / ".git").is_dir():
        return jsonify({"status": "ok", "message": "Already a git repository"})

    ok, out = _git_init(target)
    if ok:
        return jsonify({"status": "ok", "message": "Initialized git repository"})
    return jsonify({"error": out}), 500


@app.route("/api/git/info", methods=["GET"])
@requires_auth
def git_info():
    """Get git info (repo status, remote, branch) for a directory."""
    subdir = request.args.get("dir", "")
    target = safe_path(subdir) if subdir else documents_dir
    if target is None or not target.is_dir():
        return jsonify({"is_repo": False})

    git_root = _find_git_root(target)
    if not git_root:
        return jsonify({"is_repo": False})

    ok_r, remote = _git_run(git_root, "remote", "get-url", "origin")
    ok_b, branch = _git_run(git_root, "symbolic-ref", "--short", "HEAD")

    return jsonify({
        "is_repo": True,
        "remote": remote if ok_r else "",
        "branch": branch if ok_b else "main",
    })


@app.route("/api/git/remote", methods=["POST"])
@requires_auth
def git_set_remote():
    """Set or update the remote origin URL."""
    data = request.get_json()
    subdir = data.get("dir", "")
    url = data.get("url", "").strip()
    if not url:
        return jsonify({"error": "URL required"}), 400

    target = safe_path(subdir) if subdir else documents_dir
    if target is None:
        return jsonify({"error": "Invalid directory"}), 400

    git_root = _find_git_root(target)
    if not git_root:
        return jsonify({"error": "Not a git repository"}), 400

    # Check if remote already exists
    ok, _ = _git_run(git_root, "remote", "get-url", "origin")
    if ok:
        ok, out = _git_run(git_root, "remote", "set-url", "origin", url)
    else:
        ok, out = _git_run(git_root, "remote", "add", "origin", url)

    if ok:
        return jsonify({"status": "ok"})
    return jsonify({"error": out}), 400


@app.route("/api/git/push", methods=["POST"])
@requires_auth
def git_push():
    """Push current branch to remote origin."""
    data = request.get_json()
    subdir = data.get("dir", "")
    target = safe_path(subdir) if subdir else documents_dir
    if target is None:
        return jsonify({"error": "Invalid directory"}), 400

    git_root = _find_git_root(target)
    if not git_root:
        return jsonify({"error": "Not a git repository"}), 400

    ok_b, branch = _git_run(git_root, "symbolic-ref", "--short", "HEAD")
    branch = branch if ok_b else "main"

    ok, out = _git_run(git_root, "push", "-u", "origin", branch)
    if ok:
        return jsonify({"status": "ok", "message": out or "Pushed successfully"})
    return jsonify({"error": out}), 400


# --- WebSocket Events ---

def register_socket_events(socketio):
    """Register all WebSocket event handlers."""
    from flask_socketio import emit

    @socketio.on("connect")
    def handle_connect():
        # Browser sends Basic Auth creds on the polling handshake request.
        # If auth headers are present, verify them. The page itself is
        # already behind auth, so if no auth header (e.g. websocket upgrade),
        # allow the connection.
        auth = request.authorization
        if auth and not check_auth(auth.username, auth.password):
            return False

    @socketio.on("request_outline")
    def handle_outline(data):
        """Parse document and return outline."""
        content = data.get("content", "")
        cursor_line = data.get("cursor_line", 1)

        outline = parse_markdown(content)
        current = get_current_section(outline, cursor_line)

        items = []
        lines = content.split("\n") if isinstance(content, str) else content

        for item in outline.items:
            is_empty = _is_section_empty(item, lines)
            items.append({
                "level": item.level,
                "text": item.text,
                "line_number": item.line_number,
                "item_type": item.item_type,
                "is_current": item == current,
                "is_empty": is_empty,
            })

        emit("outline_result", {
            "items": items,
            "title": outline.title,
            "word_count": outline.word_count,
            "line_count": outline.line_count,
        })

    @socketio.on("request_suggestions")
    def handle_suggestions(data):
        """Generate AI suggestions in background thread."""
        sid = request.sid  # capture before background thread

        def do_suggestions():
            content = data.get("content", "")
            cursor_line = data.get("cursor_line", 1)
            current_line_text = data.get("current_line_text", "")
            filename = data.get("filename", "document.md")

            lines = content.split("\n")
            is_empty = not current_line_text.strip()

            para_before, current_para, para_after = extract_paragraphs(lines, cursor_line)

            mode = "next_paragraph" if (is_empty or not current_para.strip()) else "alternatives"

            context = WritingContext(
                full_document=content,
                current_paragraph=current_para,
                paragraph_before=para_before,
                paragraph_after=para_after,
                cursor_line=cursor_line,
                filename=filename,
                document_type="markdown",
                is_empty_line=is_empty,
            )

            try:
                suggestions = ai_provider.generate_suggestions(
                    context,
                    count=writer_config.display.suggestion_count,
                )
                result = [{"text": s.text, "confidence": s.confidence, "description": s.description}
                          for s in suggestions]
            except Exception as e:
                result = [{"text": f"[Error: {e}]", "confidence": 0, "description": "Error"}]

            socketio.emit("suggestions_result", {"suggestions": result, "mode": mode}, to=sid)

        socketio.start_background_task(do_suggestions)

    @socketio.on("request_review")
    def handle_review(data):
        """Generate AI review in background thread."""
        sid = request.sid  # capture before background thread

        def do_review():
            content = data.get("content", "")
            if not content.strip():
                socketio.emit("review_result", {
                    "critique": "Document is empty.",
                    "weaknesses": "",
                    "strengths": "",
                }, to=sid)
                return

            try:
                review = ai_provider.review_document(content)
                socketio.emit("review_result", {
                    "critique": review.critique,
                    "weaknesses": review.weaknesses,
                    "strengths": review.strengths,
                }, to=sid)
            except Exception as e:
                socketio.emit("review_result", {
                    "critique": f"Error: {e}",
                    "weaknesses": "",
                    "strengths": "",
                }, to=sid)

        socketio.start_background_task(do_review)

    @socketio.on("request_fill")
    def handle_fill(data):
        """Generate section content in background thread."""
        sid = request.sid  # capture before background thread

        def do_fill():
            content = data.get("content", "")
            section_heading = data.get("heading", "")
            outline_headings = data.get("outline", [])

            if not section_heading:
                socketio.emit("fill_result", {
                    "heading": "",
                    "content": "[No section heading provided]",
                }, to=sid)
                return

            try:
                result = ai_provider.fill_section(content, section_heading, outline_headings)
                socketio.emit("fill_result", {
                    "heading": result.heading,
                    "content": result.content,
                }, to=sid)
            except Exception as e:
                socketio.emit("fill_result", {
                    "heading": section_heading,
                    "content": f"[Error: {e}]",
                }, to=sid)

        socketio.start_background_task(do_fill)

    @socketio.on("request_chat")
    def handle_chat(data):
        """Handle chat messages in background thread."""
        sid = request.sid

        def do_chat():
            document = data.get("document", "")
            raw_messages = data.get("messages", [])
            messages = [ChatMessage(role=m["role"], content=m["content"]) for m in raw_messages]

            try:
                response = ai_provider.chat(document, messages)
            except Exception as e:
                response = f"[Error: {e}]"

            socketio.emit("chat_result", {"response": response}, to=sid)

        socketio.start_background_task(do_chat)

    @socketio.on("request_inline_complete")
    def handle_inline_complete(data):
        """Handle inline autocomplete in background thread."""
        sid = request.sid

        def do_inline_complete():
            document = data.get("document", "")
            cursor_line = data.get("cursor_line", 0)
            cursor_ch = data.get("cursor_ch", 0)
            request_id = data.get("request_id", 0)

            try:
                text = ai_provider.inline_complete(document, cursor_line, cursor_ch)
            except Exception as e:
                text = ""

            socketio.emit("inline_complete_result", {
                "text": text,
                "request_id": request_id,
                "cursor_line": cursor_line,
                "cursor_ch": cursor_ch,
            }, to=sid)

        socketio.start_background_task(do_inline_complete)


def _is_section_empty(item, lines):
    """Check if a section has no content until next heading."""
    if item.item_type != "heading":
        return False
    start_line = item.line_number  # 1-indexed
    for i in range(start_line, len(lines)):
        line = lines[i]
        if i == start_line - 1:
            continue
        if line.strip().startswith("#"):
            break
        if line.strip():
            return False
    return True


if __name__ == "__main__":
    app, socketio = create_app()
    host = writer_config.web.host
    port = writer_config.web.port
    print(f"Writer Web starting on http://{host}:{port}")
    if socketio:
        socketio.run(app, host=host, port=port, debug=False, allow_unsafe_werkzeug=True)
    else:
        app.run(host=host, port=port, debug=False)
