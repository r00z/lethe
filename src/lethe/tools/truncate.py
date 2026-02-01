"""Shared truncation utilities for tool outputs.

Truncation is based on two independent limits - whichever is hit first wins:
- Line limit (default: 2000 lines)
- Byte limit (default: 50KB)

Direction-aware:
- truncate_head: for file reads (keep beginning)
- truncate_tail: for bash output (keep end where errors/results are)
"""

from dataclasses import dataclass
from typing import Optional, Literal

DEFAULT_MAX_LINES = 2000
DEFAULT_MAX_BYTES = 50 * 1024  # 50KB
GREP_MAX_LINE_LENGTH = 500  # Max chars per grep match line


@dataclass
class TruncationResult:
    """Result of a truncation operation."""
    content: str
    truncated: bool
    truncated_by: Optional[Literal["lines", "bytes"]]
    total_lines: int
    total_bytes: int
    output_lines: int
    output_bytes: int
    last_line_partial: bool = False
    first_line_exceeds_limit: bool = False
    max_lines: int = DEFAULT_MAX_LINES
    max_bytes: int = DEFAULT_MAX_BYTES


def format_size(bytes_count: int) -> str:
    """Format bytes as human-readable size."""
    if bytes_count < 1024:
        return f"{bytes_count}B"
    elif bytes_count < 1024 * 1024:
        return f"{bytes_count / 1024:.1f}KB"
    else:
        return f"{bytes_count / (1024 * 1024):.1f}MB"


def truncate_head(
    content: str,
    max_lines: int = DEFAULT_MAX_LINES,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> TruncationResult:
    """Truncate content from the head (keep first N lines/bytes).
    
    Suitable for file reads where you want to see the beginning.
    Never returns partial lines. If first line exceeds byte limit,
    returns empty content with first_line_exceeds_limit=True.
    """
    total_bytes = len(content.encode('utf-8'))
    lines = content.split('\n')
    total_lines = len(lines)
    
    # Check if no truncation needed
    if total_lines <= max_lines and total_bytes <= max_bytes:
        return TruncationResult(
            content=content,
            truncated=False,
            truncated_by=None,
            total_lines=total_lines,
            total_bytes=total_bytes,
            output_lines=total_lines,
            output_bytes=total_bytes,
            max_lines=max_lines,
            max_bytes=max_bytes,
        )
    
    # Check if first line alone exceeds byte limit
    first_line_bytes = len(lines[0].encode('utf-8'))
    if first_line_bytes > max_bytes:
        return TruncationResult(
            content="",
            truncated=True,
            truncated_by="bytes",
            total_lines=total_lines,
            total_bytes=total_bytes,
            output_lines=0,
            output_bytes=0,
            first_line_exceeds_limit=True,
            max_lines=max_lines,
            max_bytes=max_bytes,
        )
    
    # Collect complete lines that fit
    output_lines_arr = []
    output_bytes_count = 0
    truncated_by: Literal["lines", "bytes"] = "lines"
    
    for i, line in enumerate(lines):
        if i >= max_lines:
            break
            
        line_bytes = len(line.encode('utf-8')) + (1 if i > 0 else 0)  # +1 for newline
        
        if output_bytes_count + line_bytes > max_bytes:
            truncated_by = "bytes"
            break
        
        output_lines_arr.append(line)
        output_bytes_count += line_bytes
    
    # If we exited due to line limit
    if len(output_lines_arr) >= max_lines and output_bytes_count <= max_bytes:
        truncated_by = "lines"
    
    output_content = '\n'.join(output_lines_arr)
    final_output_bytes = len(output_content.encode('utf-8'))
    
    return TruncationResult(
        content=output_content,
        truncated=True,
        truncated_by=truncated_by,
        total_lines=total_lines,
        total_bytes=total_bytes,
        output_lines=len(output_lines_arr),
        output_bytes=final_output_bytes,
        max_lines=max_lines,
        max_bytes=max_bytes,
    )


def truncate_tail(
    content: str,
    max_lines: int = DEFAULT_MAX_LINES,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> TruncationResult:
    """Truncate content from the tail (keep last N lines/bytes).
    
    Suitable for bash output where you want to see the end (errors, final results).
    May return partial first line if the last line of original content exceeds byte limit.
    """
    total_bytes = len(content.encode('utf-8'))
    lines = content.split('\n')
    total_lines = len(lines)
    
    # Check if no truncation needed
    if total_lines <= max_lines and total_bytes <= max_bytes:
        return TruncationResult(
            content=content,
            truncated=False,
            truncated_by=None,
            total_lines=total_lines,
            total_bytes=total_bytes,
            output_lines=total_lines,
            output_bytes=total_bytes,
            max_lines=max_lines,
            max_bytes=max_bytes,
        )
    
    # Work backwards from the end
    output_lines_arr = []
    output_bytes_count = 0
    truncated_by: Literal["lines", "bytes"] = "lines"
    last_line_partial = False
    
    for i in range(len(lines) - 1, -1, -1):
        if len(output_lines_arr) >= max_lines:
            break
            
        line = lines[i]
        line_bytes = len(line.encode('utf-8')) + (1 if output_lines_arr else 0)  # +1 for newline
        
        if output_bytes_count + line_bytes > max_bytes:
            truncated_by = "bytes"
            # Edge case: if we haven't added ANY lines yet and this line exceeds max_bytes,
            # take the end of the line (partial)
            if not output_lines_arr:
                truncated_line = _truncate_string_from_end(line, max_bytes)
                output_lines_arr.insert(0, truncated_line)
                output_bytes_count = len(truncated_line.encode('utf-8'))
                last_line_partial = True
            break
        
        output_lines_arr.insert(0, line)
        output_bytes_count += line_bytes
    
    # If we exited due to line limit
    if len(output_lines_arr) >= max_lines and output_bytes_count <= max_bytes:
        truncated_by = "lines"
    
    output_content = '\n'.join(output_lines_arr)
    final_output_bytes = len(output_content.encode('utf-8'))
    
    return TruncationResult(
        content=output_content,
        truncated=True,
        truncated_by=truncated_by,
        total_lines=total_lines,
        total_bytes=total_bytes,
        output_lines=len(output_lines_arr),
        output_bytes=final_output_bytes,
        last_line_partial=last_line_partial,
        max_lines=max_lines,
        max_bytes=max_bytes,
    )


def _truncate_string_from_end(s: str, max_bytes: int) -> str:
    """Truncate a string to fit within a byte limit (from the end).
    
    Handles multi-byte UTF-8 characters correctly.
    """
    encoded = s.encode('utf-8')
    if len(encoded) <= max_bytes:
        return s
    
    # Take the last max_bytes, but ensure we don't break a multi-byte character
    truncated = encoded[-max_bytes:]
    
    # Skip incomplete UTF-8 sequences at the start
    # UTF-8 continuation bytes start with 10xxxxxx (0x80-0xBF)
    i = 0
    while i < len(truncated) and (truncated[i] & 0xC0) == 0x80:
        i += 1
    
    return truncated[i:].decode('utf-8', errors='replace')


def truncate_line(line: str, max_chars: int = GREP_MAX_LINE_LENGTH) -> tuple[str, bool]:
    """Truncate a single line to max characters, adding [truncated] suffix.
    
    Used for grep match lines.
    
    Returns:
        Tuple of (truncated_text, was_truncated)
    """
    if len(line) <= max_chars:
        return line, False
    return f"{line[:max_chars]}... [truncated]", True


def format_truncation_notice(
    result: TruncationResult,
    start_line: int = 1,
    temp_file_path: Optional[str] = None,
) -> str:
    """Format a truncation notice to append to output.
    
    Provides actionable guidance on how to get more content.
    """
    if not result.truncated:
        return ""
    
    end_line = start_line + result.output_lines - 1
    next_offset = end_line + 1
    
    if result.first_line_exceeds_limit:
        first_line_size = format_size(result.total_bytes // result.total_lines)  # Approximate
        return f"[Line {start_line} is ~{first_line_size}, exceeds {format_size(result.max_bytes)} limit. Use bash: sed -n '{start_line}p' <file> | head -c {result.max_bytes}]"
    
    if result.last_line_partial:
        if temp_file_path:
            return f"[Showing last {format_size(result.output_bytes)} of line {result.total_lines}. Full output: {temp_file_path}]"
        return f"[Showing last {format_size(result.output_bytes)} of line {result.total_lines}]"
    
    if result.truncated_by == "lines":
        notice = f"[Showing lines {start_line}-{end_line} of {result.total_lines}. Use offset={next_offset} to continue.]"
    else:  # bytes
        notice = f"[Showing lines {start_line}-{end_line} of {result.total_lines} ({format_size(result.max_bytes)} limit). Use offset={next_offset} to continue.]"
    
    if temp_file_path:
        notice = notice[:-1] + f" Full output: {temp_file_path}]"
    
    return notice
