import difflib
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class DiffSegment(BaseModel):
    """A single segment of a diff with change type and content."""
    
    change_type: str = Field(..., description="Type of change: 'added', 'removed', or 'unchanged'")
    content: str = Field(..., description="The content of this segment")
    position: int = Field(..., description="Position in the original text")
    length: int = Field(..., description="Length of this segment")


class DiffResult(BaseModel):
    """Structured diff result with statistics and segments."""
    
    original: str = Field(..., description="Original text")
    modified: str = Field(..., description="Modified text")
    segments: List[DiffSegment] = Field(default_factory=list, description="List of diff segments")
    additions: int = Field(default=0, description="Number of additions")
    deletions: int = Field(default=0, description="Number of deletions")
    unchanged: int = Field(default=0, description="Number of unchanged segments")
    similarity_ratio: float = Field(..., description="Similarity ratio (0.0 to 1.0)")
    
    def get_diff_summary(self) -> str:
        """Get a human-readable summary of the diff."""
        total_changes = self.additions + self.deletions
        if total_changes == 0:
            return "No changes"
        
        parts = []
        if self.additions > 0:
            parts.append(f"{self.additions} addition(s)")
        if self.deletions > 0:
            parts.append(f"{self.deletions} deletion(s)")
        
        return f"{', '.join(parts)} ({self.similarity_ratio:.1%} similar)"


class DiffEngine:
    """Token-level diff engine for comparing prompt versions."""
    
    def __init__(self, token_type: str = "word"):
        """Initialize the diff engine.
        
        Args:
            token_type: Type of tokenization ('word', 'line', or 'character')
        """
        self.token_type = token_type
    
    def tokenize(self, text: str) -> List[str]:
        """Tokenize text based on the configured token type.
        
        Args:
            text: Text to tokenize
            
        Returns:
            List of tokens
        """
        if self.token_type == "word":
            return text.split()
        elif self.token_type == "line":
            return text.splitlines()
        elif self.token_type == "character":
            return list(text)
        else:
            return text.split()
    
    def detokenize(self, tokens: List[str]) -> str:
        """Convert tokens back to text.
        
        Args:
            tokens: List of tokens
            
        Returns:
            Reconstructed text
        """
        if self.token_type == "word":
            return " ".join(tokens)
        elif self.token_type == "line":
            return "\n".join(tokens)
        elif self.token_type == "character":
            return "".join(tokens)
        else:
            return " ".join(tokens)
    
    def diff(self, original: str, modified: str) -> DiffResult:
        """Generate a structured diff between two texts.
        
        Args:
            original: Original text
            modified: Modified text
            
        Returns:
            Structured diff result
        """
        # Tokenize both texts
        original_tokens = self.tokenize(original)
        modified_tokens = self.tokenize(modified)
        
        # Calculate similarity ratio
        similarity = difflib.SequenceMatcher(
            None, original_tokens, modified_tokens
        ).ratio()
        
        # Generate diff using difflib
        matcher = difflib.SequenceMatcher(None, original_tokens, modified_tokens)
        
        segments = []
        additions = 0
        deletions = 0
        unchanged = 0
        position = 0
        
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == "equal":
                # Unchanged segment
                content = self.detokenize(original_tokens[i1:i2])
                segments.append(DiffSegment(
                    change_type="unchanged",
                    content=content,
                    position=position,
                    length=len(content),
                ))
                unchanged += 1
                position += len(content)
            elif tag == "replace":
                # Replacement (deletion + addition)
                deleted_content = self.detokenize(original_tokens[i1:i2])
                added_content = self.detokenize(modified_tokens[j1:j2])
                
                if deleted_content:
                    segments.append(DiffSegment(
                        change_type="removed",
                        content=deleted_content,
                        position=position,
                        length=len(deleted_content),
                    ))
                    deletions += 1
                
                if added_content:
                    segments.append(DiffSegment(
                        change_type="added",
                        content=added_content,
                        position=position,
                        length=len(added_content),
                    ))
                    additions += 1
                
                position += max(len(deleted_content), len(added_content))
            elif tag == "delete":
                # Deletion
                deleted_content = self.detokenize(original_tokens[i1:i2])
                segments.append(DiffSegment(
                    change_type="removed",
                    content=deleted_content,
                    position=position,
                    length=len(deleted_content),
                ))
                deletions += 1
                position += len(deleted_content)
            elif tag == "insert":
                # Insertion
                added_content = self.detokenize(modified_tokens[j1:j2])
                segments.append(DiffSegment(
                    change_type="added",
                    content=added_content,
                    position=position,
                    length=len(added_content),
                ))
                additions += 1
                position += len(added_content)
        
        return DiffResult(
            original=original,
            modified=modified,
            segments=segments,
            additions=additions,
            deletions=deletions,
            unchanged=unchanged,
            similarity_ratio=similarity,
        )
    
    def diff_html(self, original: str, modified: str) -> str:
        """Generate an HTML-formatted diff.
        
        Args:
            original: Original text
            modified: Modified text
            
        Returns:
            HTML string with diff highlighting
        """
        diff_result = self.diff(original, modified)
        
        html_parts = []
        for segment in diff_result.segments:
            if segment.change_type == "added":
                html_parts.append(f'<span class="diff-added">{segment.content}</span>')
            elif segment.change_type == "removed":
                html_parts.append(f'<span class="diff-removed">{segment.content}</span>')
            else:
                html_parts.append(f'<span class="diff-unchanged">{segment.content}</span>')
        
        return "".join(html_parts)
    
    def diff_unified(self, original: str, modified: str, context_lines: int = 3) -> str:
        """Generate a unified diff format.
        
        Args:
            original: Original text
            modified: Modified text
            context_lines: Number of context lines to show
            
        Returns:
            Unified diff string
        """
        original_lines = original.splitlines(keepends=True)
        modified_lines = modified.splitlines(keepends=True)
        
        return "".join(
            difflib.unified_diff(
                original_lines,
                modified_lines,
                fromfile="original",
                tofile="modified",
                n=context_lines,
            )
        )
    
    def get_line_diff(self, original: str, modified: str) -> Dict[str, Any]:
        """Get line-by-line diff statistics.
        
        Args:
            original: Original text
            modified: Modified text
            
        Returns:
            Dictionary with line-level diff statistics
        """
        original_lines = original.splitlines()
        modified_lines = modified.splitlines()
        
        matcher = difflib.SequenceMatcher(None, original_lines, modified_lines)
        
        line_changes = []
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == "equal":
                continue
            
            line_changes.append({
                "type": tag,
                "original_lines": original_lines[i1:i2],
                "modified_lines": modified_lines[j1:j2],
                "original_start": i1,
                "modified_start": j1,
            })
        
        return {
            "total_lines_original": len(original_lines),
            "total_lines_modified": len(modified_lines),
            "line_changes": line_changes,
            "changed_line_count": sum(
                len(change["original_lines"]) + len(change["modified_lines"])
                for change in line_changes
            ),
        }


class PromptDiffEngine(DiffEngine):
    """Specialized diff engine for prompt templates with variable awareness."""
    
    def __init__(self, variable_marker: str = "{{"):
        """Initialize the prompt diff engine.
        
        Args:
            variable_marker: Marker for template variables (default: '{{')
        """
        super().__init__(token_type="word")
        self.variable_marker = variable_marker
    
    def extract_variables(self, template: str) -> List[str]:
        """Extract variable names from a template.
        
        Args:
            template: Template string
            
        Returns:
            List of variable names
        """
        import re
        pattern = rf"\{self.variable_marker}\s*(\w+)\s*\}}"
        return re.findall(pattern, template)
    
    def diff_with_variables(
        self,
        original: str,
        modified: str,
    ) -> Dict[str, Any]:
        """Generate diff with variable change analysis.
        
        Args:
            original: Original template
            modified: Modified template
            
        Returns:
            Dictionary with diff and variable analysis
        """
        # Get standard diff
        diff_result = self.diff(original, modified)
        
        # Extract variables from both versions
        original_vars = set(self.extract_variables(original))
        modified_vars = set(self.extract_variables(modified))
        
        # Analyze variable changes
        added_vars = modified_vars - original_vars
        removed_vars = original_vars - modified_vars
        unchanged_vars = original_vars & modified_vars
        
        return {
            "diff": diff_result.model_dump(),
            "variables": {
                "original": sorted(original_vars),
                "modified": sorted(modified_vars),
                "added": sorted(added_vars),
                "removed": sorted(removed_vars),
                "unchanged": sorted(unchanged_vars),
            },
        }
