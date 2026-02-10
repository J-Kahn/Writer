"""
AI Client - OpenAI and Claude API wrapper for writing suggestions.

Provides a unified interface for generating writing suggestions
from both OpenAI GPT models and Anthropic Claude models.
"""

from abc import ABC, abstractmethod
from typing import Optional
from dataclasses import dataclass

from config import load_config, WriterConfig


@dataclass
class WritingContext:
    """Context for generating writing suggestions."""
    full_document: str      # Full document for context
    current_paragraph: str  # Current paragraph to continue
    paragraph_before: str   # Paragraph before current
    paragraph_after: str    # Paragraph after current
    cursor_line: int        # Cursor line number
    filename: str           # Document filename
    document_type: str      # "markdown", "text", etc.
    is_empty_line: bool = False  # Whether cursor is on empty line


@dataclass
class Suggestion:
    """A single writing suggestion."""
    text: str               # Suggested text
    confidence: float       # 0.0 to 1.0
    description: str        # Brief description of what this adds


@dataclass
class SectionContent:
    """Generated content for a section."""
    heading: str            # The section heading
    content: str            # Generated content


@dataclass
class ChatMessage:
    """A single chat message."""
    role: str                   # "user" or "assistant"
    content: str                # Message text


@dataclass
class DocumentReview:
    """AI review/critique of the document."""
    critique: str               # Free-form critical analysis
    weaknesses: str             # What's not working and why
    strengths: str              # What's working well


class AIProvider(ABC):
    """Abstract base class for AI providers."""

    @abstractmethod
    def generate_suggestions(
        self,
        context: WritingContext,
        count: int = 3
    ) -> list[Suggestion]:
        """Generate writing suggestions for current paragraph."""
        pass

    @abstractmethod
    def fill_section(
        self,
        document: str,
        section_heading: str,
        outline: list[str]
    ) -> SectionContent:
        """Generate content for a section based on its heading and document context."""
        pass

    @abstractmethod
    def review_document(self, document: str) -> DocumentReview:
        """Review document for readability and argument strength."""
        pass

    @abstractmethod
    def chat(self, document: str, messages: list[ChatMessage]) -> str:
        """Chat about the document. Returns assistant response text."""
        pass

    @abstractmethod
    def inline_complete(self, document: str, cursor_line: int, cursor_ch: int) -> str:
        """Generate inline text completion at cursor position. Returns continuation text."""
        pass


class OpenAIProvider(AIProvider):
    """OpenAI GPT provider."""

    def __init__(self, api_key: str, model: str = "gpt-4", writing_style: str = None):
        self.api_key = api_key
        self.model = model
        self.writing_style = writing_style
        self._client = None

    @property
    def client(self):
        if self._client is None:
            from openai import OpenAI
            self._client = OpenAI(api_key=self.api_key)
        return self._client

    def generate_suggestions(
        self,
        context: WritingContext,
        count: int = 3
    ) -> list[Suggestion]:
        """Generate paragraph continuation suggestions using GPT."""
        prompt = self._build_paragraph_prompt(context, count)

        try:
            system_content = (
                "You are a writing assistant. You help in two ways:\n"
                "1. When given a paragraph, suggest alternative phrasings that keep the same meaning\n"
                "2. When the user is on an empty line, suggest the next paragraph\n"
                "Always match the document's tone and style. Output clean text only."
            )
            if self.writing_style:
                system_content += f"\n\nThe user has specified this writing style preference:\n{self.writing_style}"

            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_content},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.7,
                max_completion_tokens=500
            )

            return self._parse_suggestions(response.choices[0].message.content, count)

        except Exception as e:
            return [Suggestion(
                text=f"[Error: {str(e)}]",
                confidence=0.0,
                description="API error"
            )]

    def fill_section(
        self,
        document: str,
        section_heading: str,
        outline: list[str]
    ) -> SectionContent:
        """Generate content for a section."""
        prompt = f"""You are writing content for a document. Here is the current document:

---
{document[:3000]}
---

The document outline is:
{chr(10).join('- ' + h for h in outline)}

Please write content for the section titled: "{section_heading}"

Requirements:
- Write 2-4 paragraphs appropriate for this section
- Match the tone and style of existing content
- Connect logically to surrounding sections
- Be substantive but concise

Write only the section content, no heading."""

        try:
            system_content = "You are a skilled writer helping complete a document."
            if self.writing_style:
                system_content += f"\n\nFollow this writing style preference:\n{self.writing_style}"

            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_content},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.7,
                max_completion_tokens=800
            )

            return SectionContent(
                heading=section_heading,
                content=response.choices[0].message.content.strip()
            )

        except Exception as e:
            return SectionContent(
                heading=section_heading,
                content=f"[Error generating content: {str(e)}]"
            )

    def review_document(self, document: str) -> DocumentReview:
        """Review document like a tough editor/prosecuting attorney."""
        prompt = f"""Review this document as a critical editor and prosecuting attorney.

Document:
---
{document[:4000]}
---

Respond with exactly ONE sentence for each section:

CRITIQUE: [One sentence - your honest editorial assessment]

WEAKNESSES: [One sentence - the key hole in the argument, like a prosecutor would find]

STRENGTHS: [One sentence - what's working well]"""

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a sharp, experienced editor with high standards. "
                            "You give honest, specific feedback - not generic praise or vague criticism. "
                            "When you find problems, you explain exactly what's wrong and why it matters."
                        )
                    },
                    {"role": "user", "content": prompt}
                ],
                temperature=0.6,
                max_completion_tokens=1000
            )

            return self._parse_review(response.choices[0].message.content)

        except Exception as e:
            return DocumentReview(
                critique=f"Error: {str(e)}",
                weaknesses="",
                strengths=""
            )

    def chat(self, document: str, messages: list[ChatMessage]) -> str:
        """Chat about the document using GPT."""
        try:
            system_content = (
                "You are a helpful writing assistant. The user is working on a document and may ask "
                "questions about it, request edits, brainstorm ideas, or discuss their writing.\n\n"
                f"Here is the document they are working on (truncated):\n---\n{document[:4000]}\n---\n\n"
                "Be concise and helpful. Reference specific parts of the document when relevant."
            )
            if self.writing_style:
                system_content += f"\n\nThe user's writing style preference:\n{self.writing_style}"

            api_messages = []
            for m in messages[-10:]:
                api_messages.append({"role": m.role, "content": m.content})

            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "system", "content": system_content}] + api_messages,
                temperature=0.7,
                max_completion_tokens=500,
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            return f"[Error: {e}]"

    def inline_complete(self, document: str, cursor_line: int, cursor_ch: int) -> str:
        """Generate inline completion at cursor position."""
        try:
            lines = document.split('\n')
            # Get text before cursor (last 1500 chars)
            before_lines = lines[:cursor_line]
            if cursor_line < len(lines):
                before_lines.append(lines[cursor_line][:cursor_ch])
            text_before = '\n'.join(before_lines)[-1500:]

            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are a writing autocomplete engine. Output ONLY the natural continuation of the text. Write 1-2 sentences max. No explanations, no quotes, no prefixes."},
                    {"role": "user", "content": f"Continue this text naturally:\n\n{text_before}"},
                ],
                temperature=0.3,
                max_completion_tokens=100,
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            return ""

    def _parse_review(self, response: str) -> DocumentReview:
        """Parse review response into structured format."""
        text = response.strip()

        def extract_section(name: str) -> str:
            """Extract content after a section header."""
            markers = [f"{name}:", f"**{name}**:", f"**{name}:**", f"#{name}", f"## {name}"]
            for marker in markers:
                if marker.upper() in text.upper():
                    idx = text.upper().find(marker.upper())
                    start = idx + len(marker)
                    # Find next section or end
                    next_sections = ["CRITIQUE", "WEAKNESSES", "STRENGTHS"]
                    end = len(text)
                    for ns in next_sections:
                        if ns.upper() != name.upper():
                            for m in [f"{ns}:", f"**{ns}**:", f"**{ns}:**", f"#{ns}", f"## {ns}"]:
                                pos = text.upper().find(m.upper(), start)
                                if pos != -1 and pos < end:
                                    end = pos
                    return text[start:end].strip()
            return ""

        return DocumentReview(
            critique=extract_section("CRITIQUE"),
            weaknesses=extract_section("WEAKNESSES"),
            strengths=extract_section("STRENGTHS")
        )

    def _build_paragraph_prompt(self, context: WritingContext, count: int) -> str:
        """Build prompt based on whether we're rewriting or generating new."""

        if context.is_empty_line or not context.current_paragraph.strip():
            # Empty line - generate next paragraph
            return f"""Document so far:
---
{context.full_document[:2500]}
---

The previous paragraph was:
"{context.paragraph_before}"

The user's cursor is on an empty line and they want to write the next paragraph.

Generate {count} different options for the NEXT paragraph. Rules:
- Write a complete paragraph (2-4 sentences)
- Flow naturally from what came before
- Advance the document's narrative or argument
- Match the tone and style

Output format:
SUGGESTION 1:
[full paragraph]

SUGGESTION 2:
[full paragraph]

SUGGESTION 3:
[full paragraph]"""
        else:
            # Has text - suggest alternative phrasings
            return f"""Document context:
---
{context.full_document[:2500]}
---

The user has written this paragraph:
"{context.current_paragraph}"

Generate {count} ALTERNATIVE ways to phrase this same paragraph. Rules:
- Keep the same meaning and intent
- Vary the sentence structure, word choice, or flow
- Each alternative should be a complete replacement for the paragraph
- Match the document's overall tone
- Similar length to the original

Output format:
SUGGESTION 1:
[alternative phrasing of the paragraph]

SUGGESTION 2:
[alternative phrasing of the paragraph]

SUGGESTION 3:
[alternative phrasing of the paragraph]"""

    def _parse_suggestions(self, response: str, count: int) -> list[Suggestion]:
        """Parse suggestions from API response."""
        suggestions = []
        parts = response.split('SUGGESTION')

        for i, part in enumerate(parts[1:count+1], 1):
            text = part.strip()
            if text.startswith(f'{i}:'):
                text = text[2:].strip()
            elif text.startswith(':'):
                text = text[1:].strip()

            if text:
                suggestions.append(Suggestion(
                    text=text,
                    confidence=0.8 - (i * 0.1),
                    description=f"Option {i}"
                ))

        if not suggestions:
            suggestions.append(Suggestion(
                text=response.strip(),
                confidence=0.5,
                description="Continuation"
            ))

        return suggestions


class ClaudeProvider(AIProvider):
    """Anthropic Claude provider."""

    def __init__(self, api_key: str, model: str = "claude-sonnet-4-20250514", writing_style: str = None):
        self.api_key = api_key
        self.model = model
        self.writing_style = writing_style
        self._client = None

    @property
    def client(self):
        if self._client is None:
            from anthropic import Anthropic
            self._client = Anthropic(api_key=self.api_key)
        return self._client

    def generate_suggestions(
        self,
        context: WritingContext,
        count: int = 3
    ) -> list[Suggestion]:
        """Generate paragraph continuation suggestions using Claude."""
        prompt = self._build_paragraph_prompt(context, count)

        try:
            system_content = (
                "You are a writing assistant. You help in two ways:\n"
                "1. When given a paragraph, suggest alternative phrasings that keep the same meaning\n"
                "2. When the user is on an empty line, suggest the next paragraph\n"
                "Always match the document's tone and style. Output clean text only."
            )
            if self.writing_style:
                system_content += f"\n\nThe user has specified this writing style preference:\n{self.writing_style}"

            response = self.client.messages.create(
                model=self.model,
                max_tokens=500,
                messages=[
                    {"role": "user", "content": prompt}
                ],
                system=system_content
            )

            return self._parse_suggestions(response.content[0].text, count)

        except Exception as e:
            return [Suggestion(
                text=f"[Error: {str(e)}]",
                confidence=0.0,
                description="API error"
            )]

    def fill_section(
        self,
        document: str,
        section_heading: str,
        outline: list[str]
    ) -> SectionContent:
        """Generate content for a section."""
        prompt = f"""You are writing content for a document. Here is the current document:

---
{document[:3000]}
---

The document outline is:
{chr(10).join('- ' + h for h in outline)}

Please write content for the section titled: "{section_heading}"

Requirements:
- Write 2-4 paragraphs appropriate for this section
- Match the tone and style of existing content
- Connect logically to surrounding sections
- Be substantive but concise

Write only the section content, no heading."""

        try:
            system_content = "You are a skilled writer helping complete a document."
            if self.writing_style:
                system_content += f"\n\nFollow this writing style preference:\n{self.writing_style}"

            response = self.client.messages.create(
                model=self.model,
                max_tokens=800,
                messages=[
                    {"role": "user", "content": prompt}
                ],
                system=system_content
            )

            return SectionContent(
                heading=section_heading,
                content=response.content[0].text.strip()
            )

        except Exception as e:
            return SectionContent(
                heading=section_heading,
                content=f"[Error generating content: {str(e)}]"
            )

    def review_document(self, document: str) -> DocumentReview:
        """Review document like a tough editor/prosecuting attorney."""
        prompt = f"""Review this document as a critical editor and prosecuting attorney.

Document:
---
{document[:4000]}
---

Respond with exactly ONE sentence for each section:

CRITIQUE: [One sentence - your honest editorial assessment]

WEAKNESSES: [One sentence - the key hole in the argument, like a prosecutor would find]

STRENGTHS: [One sentence - what's working well]"""

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=1000,
                messages=[
                    {"role": "user", "content": prompt}
                ],
                system=(
                    "You are a sharp, experienced editor with high standards. "
                    "You give honest, specific feedback - not generic praise or vague criticism. "
                    "When you find problems, you explain exactly what's wrong and why it matters."
                )
            )

            return self._parse_review(response.content[0].text)

        except Exception as e:
            return DocumentReview(
                critique=f"Error: {str(e)}",
                weaknesses="",
                strengths=""
            )

    def chat(self, document: str, messages: list[ChatMessage]) -> str:
        """Chat about the document using Claude."""
        try:
            system_content = (
                "You are a helpful writing assistant. The user is working on a document and may ask "
                "questions about it, request edits, brainstorm ideas, or discuss their writing.\n\n"
                f"Here is the document they are working on (truncated):\n---\n{document[:4000]}\n---\n\n"
                "Be concise and helpful. Reference specific parts of the document when relevant."
            )
            if self.writing_style:
                system_content += f"\n\nThe user's writing style preference:\n{self.writing_style}"

            api_messages = []
            for m in messages[-10:]:
                api_messages.append({"role": m.role, "content": m.content})

            response = self.client.messages.create(
                model=self.model,
                max_tokens=500,
                messages=api_messages,
                system=system_content,
            )
            return response.content[0].text.strip()
        except Exception as e:
            return f"[Error: {e}]"

    def inline_complete(self, document: str, cursor_line: int, cursor_ch: int) -> str:
        """Generate inline completion at cursor position."""
        try:
            lines = document.split('\n')
            before_lines = lines[:cursor_line]
            if cursor_line < len(lines):
                before_lines.append(lines[cursor_line][:cursor_ch])
            text_before = '\n'.join(before_lines)[-1500:]

            response = self.client.messages.create(
                model=self.model,
                max_tokens=100,
                messages=[
                    {"role": "user", "content": f"Continue this text naturally:\n\n{text_before}"},
                ],
                system="You are a writing autocomplete engine. Output ONLY the natural continuation of the text. Write 1-2 sentences max. No explanations, no quotes, no prefixes.",
            )
            return response.content[0].text.strip()
        except Exception as e:
            return ""

    def _parse_review(self, response: str) -> DocumentReview:
        """Parse review response into structured format."""
        text = response.strip()

        def extract_section(name: str) -> str:
            """Extract content after a section header."""
            markers = [f"{name}:", f"**{name}**:", f"**{name}:**", f"#{name}", f"## {name}"]
            for marker in markers:
                if marker.upper() in text.upper():
                    idx = text.upper().find(marker.upper())
                    start = idx + len(marker)
                    # Find next section or end
                    next_sections = ["CRITIQUE", "WEAKNESSES", "STRENGTHS"]
                    end = len(text)
                    for ns in next_sections:
                        if ns.upper() != name.upper():
                            for m in [f"{ns}:", f"**{ns}**:", f"**{ns}:**", f"#{ns}", f"## {ns}"]:
                                pos = text.upper().find(m.upper(), start)
                                if pos != -1 and pos < end:
                                    end = pos
                    return text[start:end].strip()
            return ""

        return DocumentReview(
            critique=extract_section("CRITIQUE"),
            weaknesses=extract_section("WEAKNESSES"),
            strengths=extract_section("STRENGTHS")
        )

    def _build_paragraph_prompt(self, context: WritingContext, count: int) -> str:
        """Build prompt based on whether we're rewriting or generating new."""

        if context.is_empty_line or not context.current_paragraph.strip():
            # Empty line - generate next paragraph
            return f"""Document so far:
---
{context.full_document[:2500]}
---

The previous paragraph was:
"{context.paragraph_before}"

The user's cursor is on an empty line and they want to write the next paragraph.

Generate {count} different options for the NEXT paragraph. Rules:
- Write a complete paragraph (2-4 sentences)
- Flow naturally from what came before
- Advance the document's narrative or argument
- Match the tone and style

Output format:
SUGGESTION 1:
[full paragraph]

SUGGESTION 2:
[full paragraph]

SUGGESTION 3:
[full paragraph]"""
        else:
            # Has text - suggest alternative phrasings
            return f"""Document context:
---
{context.full_document[:2500]}
---

The user has written this paragraph:
"{context.current_paragraph}"

Generate {count} ALTERNATIVE ways to phrase this same paragraph. Rules:
- Keep the same meaning and intent
- Vary the sentence structure, word choice, or flow
- Each alternative should be a complete replacement for the paragraph
- Match the document's overall tone
- Similar length to the original

Output format:
SUGGESTION 1:
[alternative phrasing of the paragraph]

SUGGESTION 2:
[alternative phrasing of the paragraph]

SUGGESTION 3:
[alternative phrasing of the paragraph]"""

    def _parse_suggestions(self, response: str, count: int) -> list[Suggestion]:
        """Parse suggestions from API response."""
        suggestions = []
        parts = response.split('SUGGESTION')

        for i, part in enumerate(parts[1:count+1], 1):
            text = part.strip()
            if text.startswith(f'{i}:'):
                text = text[2:].strip()
            elif text.startswith(':'):
                text = text[1:].strip()

            if text:
                suggestions.append(Suggestion(
                    text=text,
                    confidence=0.8 - (i * 0.1),
                    description=f"Option {i}"
                ))

        if not suggestions:
            suggestions.append(Suggestion(
                text=response.strip(),
                confidence=0.5,
                description="Continuation"
            ))

        return suggestions


class MockProvider(AIProvider):
    """Mock provider for testing without API keys."""

    def generate_suggestions(
        self,
        context: WritingContext,
        count: int = 3
    ) -> list[Suggestion]:
        """Generate mock suggestions based on mode."""
        if context.is_empty_line or not context.current_paragraph.strip():
            # Next paragraph mode
            return [
                Suggestion(
                    text="Building on this foundation, we can explore the practical implications. The approach outlined above provides a framework for understanding the key challenges and opportunities that lie ahead.",
                    confidence=0.9,
                    description="Continue narrative"
                ),
                Suggestion(
                    text="However, there are important considerations to keep in mind. Not all situations will benefit equally from this approach, and careful analysis is required before implementation.",
                    confidence=0.7,
                    description="Add nuance"
                ),
                Suggestion(
                    text="The evidence supports this conclusion from multiple angles. Research in related fields has consistently shown similar patterns, lending credibility to the overall thesis.",
                    confidence=0.5,
                    description="Support argument"
                ),
            ][:count]
        else:
            # Alternatives mode
            para = context.current_paragraph[:30]
            return [
                Suggestion(
                    text=f"Here's an alternative way to express this idea, maintaining the core meaning while varying the structure and word choice for better flow.",
                    confidence=0.9,
                    description="Clearer phrasing"
                ),
                Suggestion(
                    text=f"This version takes a more direct approach, cutting unnecessary words while preserving the essential message and tone of the original.",
                    confidence=0.7,
                    description="More concise"
                ),
                Suggestion(
                    text=f"A more formal version of the same content, suitable for academic or professional contexts where precision is valued.",
                    confidence=0.5,
                    description="Formal tone"
                ),
            ][:count]

    def fill_section(
        self,
        document: str,
        section_heading: str,
        outline: list[str]
    ) -> SectionContent:
        """Generate mock section content."""
        return SectionContent(
            heading=section_heading,
            content=f"""This section covers {section_heading.lower()}.

The topic is important because it relates to the overall theme of the document. There are several key points to consider when discussing this subject.

First, we should understand the foundational concepts. Second, we can explore the practical applications. Finally, we'll examine the implications for the broader context."""
        )

    def review_document(self, document: str) -> DocumentReview:
        """Generate mock document review."""
        return DocumentReview(
            critique="The prose meanders in places—tighten the opening and cut the hedging qualifiers.",
            weaknesses="The central argument rests on an assumption that's never defended.",
            strengths="The concrete examples are vivid and the closing pulls the threads together well."
        )

    def chat(self, document: str, messages: list[ChatMessage]) -> str:
        """Return a canned chat response."""
        last_msg = messages[-1].content if messages else ""
        return f"That's an interesting point about your document. Based on what you've written, I'd suggest focusing on strengthening the core argument and adding more specific examples."

    def inline_complete(self, document: str, cursor_line: int, cursor_ch: int) -> str:
        """Return a canned inline completion."""
        return " and this leads to several important considerations worth exploring further."


def _get_model_override() -> dict:
    """Check for runtime model override from Vim."""
    import json
    from pathlib import Path
    override_file = Path.home() / ".writer" / "model_override.json"
    if override_file.exists():
        try:
            with open(override_file) as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {}


def create_provider(config: Optional[WriterConfig] = None) -> AIProvider:
    """Create an AI provider based on configuration."""
    if config is None:
        config = load_config()

    provider_name = config.ai.provider.lower()
    writing_style = config.editor.writing_style

    # Check for runtime model override
    override = _get_model_override()
    openai_model = override.get('openai_model', config.ai.openai_model)
    claude_model = override.get('claude_model', config.ai.claude_model)

    if provider_name == "openai":
        if config.ai.openai_api_key:
            return OpenAIProvider(
                api_key=config.ai.openai_api_key,
                model=openai_model,
                writing_style=writing_style
            )
    elif provider_name in ("claude", "anthropic"):
        if config.ai.anthropic_api_key:
            return ClaudeProvider(
                api_key=config.ai.anthropic_api_key,
                model=claude_model,
                writing_style=writing_style
            )

    return MockProvider()


def extract_paragraphs(lines: list[str], cursor_line: int) -> tuple[str, str, str]:
    """
    Extract current paragraph and surrounding paragraphs.

    Returns:
        Tuple of (paragraph_before, current_paragraph, paragraph_after)
    """
    # Join lines to text
    text = '\n'.join(lines)

    # Split into paragraphs (separated by blank lines)
    paragraphs = []
    current_para = []
    para_line_ranges = []  # (start_line, end_line) for each paragraph
    line_num = 1
    para_start = 1

    for line in lines:
        if line.strip() == '':
            if current_para:
                paragraphs.append('\n'.join(current_para))
                para_line_ranges.append((para_start, line_num - 1))
                current_para = []
            para_start = line_num + 1
        else:
            current_para.append(line)
        line_num += 1

    # Don't forget last paragraph
    if current_para:
        paragraphs.append('\n'.join(current_para))
        para_line_ranges.append((para_start, line_num - 1))

    # Find which paragraph contains cursor
    current_idx = 0
    for i, (start, end) in enumerate(para_line_ranges):
        if start <= cursor_line <= end:
            current_idx = i
            break

    # Extract paragraphs
    para_before = paragraphs[current_idx - 1] if current_idx > 0 else ""
    current_para = paragraphs[current_idx] if current_idx < len(paragraphs) else ""
    para_after = paragraphs[current_idx + 1] if current_idx + 1 < len(paragraphs) else ""

    return para_before, current_para, para_after


if __name__ == "__main__":
    # Test
    provider = create_provider()
    print(f"Using provider: {type(provider).__name__}")

    context = WritingContext(
        full_document="# My Document\n\nThis is the first paragraph.\n\nThis is the second paragraph that I'm writing.",
        current_paragraph="This is the second paragraph that I'm writing.",
        paragraph_before="This is the first paragraph.",
        paragraph_after="",
        cursor_line=5,
        filename="test.md",
        document_type="markdown"
    )

    suggestions = provider.generate_suggestions(context)
    for i, s in enumerate(suggestions, 1):
        print(f"\n[{i}] {s.text}")
