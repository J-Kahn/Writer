"""
Document Parser - Markdown heading and structure extraction.

Extracts document outline from markdown content including:
- Headings (# to ######)
- List items at top level
- Code block markers
"""

import re
from dataclasses import dataclass
from typing import Optional


@dataclass
class OutlineItem:
    """Represents an item in the document outline."""
    level: int          # Heading level (1-6) or 0 for other items
    text: str           # Display text
    line_number: int    # Line number in document (1-indexed)
    item_type: str      # "heading", "list", "code", "frontmatter"


@dataclass
class DocumentOutline:
    """Complete document outline."""
    items: list[OutlineItem]
    title: Optional[str]  # Document title (first h1)
    word_count: int
    line_count: int


def parse_markdown(content: str | list[str]) -> DocumentOutline:
    """
    Parse markdown content and extract outline.

    Args:
        content: Markdown content as string or list of lines

    Returns:
        DocumentOutline with extracted structure
    """
    if isinstance(content, str):
        lines = content.split('\n')
    else:
        lines = content

    items: list[OutlineItem] = []
    title: Optional[str] = None
    in_code_block = False
    in_frontmatter = False
    code_block_start: Optional[int] = None

    # Regex patterns
    heading_pattern = re.compile(r'^(#{1,6})\s+(.+)$')
    alt_h1_pattern = re.compile(r'^=+$')
    alt_h2_pattern = re.compile(r'^-+$')
    code_fence_pattern = re.compile(r'^```')
    frontmatter_pattern = re.compile(r'^---\s*$')

    for i, line in enumerate(lines):
        line_num = i + 1  # 1-indexed

        # Handle frontmatter (YAML at start of document)
        if line_num == 1 and frontmatter_pattern.match(line):
            in_frontmatter = True
            items.append(OutlineItem(
                level=0,
                text="[frontmatter]",
                line_number=line_num,
                item_type="frontmatter"
            ))
            continue

        if in_frontmatter:
            if frontmatter_pattern.match(line):
                in_frontmatter = False
            continue

        # Handle code blocks
        if code_fence_pattern.match(line):
            if not in_code_block:
                in_code_block = True
                code_block_start = line_num
                # Extract language hint if present
                lang = line[3:].strip() or "code"
                items.append(OutlineItem(
                    level=0,
                    text=f"[{lang}]",
                    line_number=line_num,
                    item_type="code"
                ))
            else:
                in_code_block = False
                code_block_start = None
            continue

        if in_code_block:
            continue

        # Check for ATX headings (# style)
        match = heading_pattern.match(line)
        if match:
            level = len(match.group(1))
            text = match.group(2).strip()

            # Remove trailing # characters
            text = re.sub(r'\s*#+\s*$', '', text)

            items.append(OutlineItem(
                level=level,
                text=text,
                line_number=line_num,
                item_type="heading"
            ))

            # Track first h1 as title
            if level == 1 and title is None:
                title = text
            continue

        # Check for Setext headings (underline style)
        if i > 0 and lines[i - 1].strip():
            prev_line = lines[i - 1].strip()
            if alt_h1_pattern.match(line) and len(line) >= 3:
                items.append(OutlineItem(
                    level=1,
                    text=prev_line,
                    line_number=line_num - 1,
                    item_type="heading"
                ))
                if title is None:
                    title = prev_line
                continue
            elif alt_h2_pattern.match(line) and len(line) >= 3:
                items.append(OutlineItem(
                    level=2,
                    text=prev_line,
                    line_number=line_num - 1,
                    item_type="heading"
                ))
                continue

    # Calculate word count
    text_content = '\n'.join(lines)
    # Remove code blocks for word count
    text_for_count = re.sub(r'```[\s\S]*?```', '', text_content)
    word_count = len(re.findall(r'\b\w+\b', text_for_count))

    return DocumentOutline(
        items=items,
        title=title,
        word_count=word_count,
        line_count=len(lines)
    )


def parse_latex(content: str | list[str]) -> DocumentOutline:
    """
    Parse LaTeX content and extract outline.

    Extracts \\part, \\chapter, \\section, \\subsection, \\subsubsection,
    and \\title commands.

    Args:
        content: LaTeX content as string or list of lines

    Returns:
        DocumentOutline with extracted structure
    """
    if isinstance(content, str):
        lines = content.split('\n')
    else:
        lines = content

    items: list[OutlineItem] = []
    title: Optional[str] = None

    # LaTeX sectioning commands and their hierarchy levels
    section_commands = {
        'part': 1,
        'chapter': 2,
        'section': 3,
        'subsection': 4,
        'subsubsection': 5,
    }

    # Pattern for sectioning commands: \section{...} or \section*{...}
    section_pattern = re.compile(
        r'\\(part|chapter|section|subsection|subsubsection)\*?\{([^}]*)\}'
    )
    title_pattern = re.compile(r'\\title\{([^}]*)\}')

    in_comment = False

    for i, line in enumerate(lines):
        line_num = i + 1
        stripped = line.strip()

        # Skip comment lines
        if stripped.startswith('%'):
            continue

        # Check for \title{...}
        title_match = title_pattern.search(line)
        if title_match and title is None:
            title = title_match.group(1).strip()

        # Check for sectioning commands
        for match in section_pattern.finditer(line):
            cmd = match.group(1)
            text = match.group(2).strip()
            level = section_commands[cmd]

            items.append(OutlineItem(
                level=level,
                text=text,
                line_number=line_num,
                item_type="heading"
            ))

    # Calculate word count - strip LaTeX commands before counting
    text_content = '\n'.join(lines)
    # Remove comments
    text_for_count = re.sub(r'%.*$', '', text_content, flags=re.MULTILINE)
    # Remove LaTeX commands
    text_for_count = re.sub(r'\\[a-zA-Z]+\*?(\{[^}]*\})*(\[[^\]]*\])*', ' ', text_for_count)
    # Remove braces and other LaTeX syntax
    text_for_count = re.sub(r'[{}\\$&~^_]', ' ', text_for_count)
    word_count = len(re.findall(r'\b\w+\b', text_for_count))

    return DocumentOutline(
        items=items,
        title=title,
        word_count=word_count,
        line_count=len(lines)
    )


def get_current_section(outline: DocumentOutline, cursor_line: int) -> Optional[OutlineItem]:
    """
    Find the heading that contains the cursor position.

    Args:
        outline: Document outline
        cursor_line: Current cursor line (1-indexed)

    Returns:
        The heading item containing cursor, or None
    """
    current_heading: Optional[OutlineItem] = None

    for item in outline.items:
        if item.item_type == "heading" and item.line_number <= cursor_line:
            current_heading = item

    return current_heading


def format_outline_text(outline: DocumentOutline, cursor_line: int = 0) -> str:
    """
    Format outline as indented text for display.

    Args:
        outline: Document outline
        cursor_line: Current cursor line for highlighting

    Returns:
        Formatted string representation
    """
    lines = []

    # Title and stats
    if outline.title:
        lines.append(f"📄 {outline.title}")
    lines.append(f"   {outline.word_count} words • {outline.line_count} lines")
    lines.append("")

    # Find current section
    current = get_current_section(outline, cursor_line)

    for item in outline.items:
        if item.item_type == "heading":
            indent = "  " * (item.level - 1)
            marker = "▸" if item == current else "•"
            prefix = "→ " if item == current else "  "
            lines.append(f"{prefix}{indent}{marker} {item.text}")
        elif item.item_type == "code":
            lines.append(f"     {item.text}")
        elif item.item_type == "frontmatter":
            lines.append(f"  ⚙ {item.text}")

    return '\n'.join(lines)


if __name__ == "__main__":
    # Test with sample markdown
    test_md = """---
title: Test Document
---

# Introduction

This is an introduction paragraph.

## Background

Some background information.

### Technical Details

```python
def hello():
    print("Hello, World!")
```

## Conclusion

Final thoughts here.

# Appendix

Additional information.
"""

    outline = parse_markdown(test_md)
    print("Document Outline:")
    print("-" * 40)
    print(format_outline_text(outline, cursor_line=10))
    print("-" * 40)
    print(f"\nTitle: {outline.title}")
    print(f"Items: {len(outline.items)}")
    print(f"Words: {outline.word_count}")
