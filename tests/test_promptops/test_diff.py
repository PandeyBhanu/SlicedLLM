import pytest
from app.promptops.diff import DiffEngine, DiffResult, PromptDiffEngine


def test_diff_engine_word_tokenization():
    """Test word-level tokenization."""
    engine = DiffEngine(token_type="word")
    tokens = engine.tokenize("The quick brown fox")
    assert tokens == ["The", "quick", "brown", "fox"]


def test_diff_engine_line_tokenization():
    """Test line-level tokenization."""
    engine = DiffEngine(token_type="line")
    tokens = engine.tokenize("Line 1\nLine 2\nLine 3")
    assert tokens == ["Line 1", "Line 2", "Line 3"]


def test_diff_engine_character_tokenization():
    """Test character-level tokenization."""
    engine = DiffEngine(token_type="character")
    tokens = engine.tokenize("abc")
    assert tokens == ["a", "b", "c"]


def test_diff_engine_detokenize():
    """Test detokenization."""
    engine = DiffEngine(token_type="word")
    text = engine.detokenize(["The", "quick", "brown", "fox"])
    assert text == "The quick brown fox"


def test_diff_engine_no_changes():
    """Test diff with no changes."""
    engine = DiffEngine(token_type="word")
    result = engine.diff("Hello world", "Hello world")
    
    assert result.original == "Hello world"
    assert result.modified == "Hello world"
    assert result.additions == 0
    assert result.deletions == 0
    assert result.similarity_ratio == 1.0


def test_diff_engine_addition():
    """Test diff with addition."""
    engine = DiffEngine(token_type="word")
    result = engine.diff("Hello", "Hello world")
    
    assert result.additions > 0
    assert result.deletions == 0
    assert result.similarity_ratio < 1.0


def test_diff_engine_deletion():
    """Test diff with deletion."""
    engine = DiffEngine(token_type="word")
    result = engine.diff("Hello world", "Hello")
    
    assert result.additions == 0
    assert result.deletions > 0
    assert result.similarity_ratio < 1.0


def test_diff_engine_replacement():
    """Test diff with replacement."""
    engine = DiffEngine(token_type="word")
    result = engine.diff("Hello world", "Hello there")
    
    assert result.additions > 0
    assert result.deletions > 0
    assert result.similarity_ratio < 1.0


def test_diff_engine_segments():
    """Test diff segments are generated correctly."""
    engine = DiffEngine(token_type="word")
    result = engine.diff("Hello world", "Hello there")
    
    assert len(result.segments) > 0
    assert all(segment.change_type in ["added", "removed", "unchanged"] for segment in result.segments)


def test_diff_engine_similarity_ratio():
    """Test similarity ratio calculation."""
    engine = DiffEngine(token_type="word")
    
    result1 = engine.diff("Hello world", "Hello world")
    assert result1.similarity_ratio == 1.0
    
    result2 = engine.diff("Hello world", "Goodbye world")
    assert 0.0 < result2.similarity_ratio < 1.0
    
    result3 = engine.diff("Hello world", "Goodbye moon")
    assert result3.similarity_ratio < result2.similarity_ratio


def test_diff_engine_html_output():
    """Test HTML diff output."""
    engine = DiffEngine(token_type="word")
    html = engine.diff_html("Hello", "Hello world")
    
    assert "diff-added" in html or "diff-unchanged" in html


def test_diff_engine_unified_output():
    """Test unified diff output."""
    engine = DiffEngine(token_type="line")
    unified = engine.diff_unified("Line 1\nLine 2", "Line 1\nLine 3")
    
    assert "--- original" in unified
    assert "+++ modified" in unified


def test_diff_engine_line_diff():
    """Test line-level diff statistics."""
    engine = DiffEngine(token_type="line")
    stats = engine.get_line_diff("Line 1\nLine 2", "Line 1\nLine 3")
    
    assert "total_lines_original" in stats
    assert "total_lines_modified" in stats
    assert "line_changes" in stats


def test_prompt_diff_engine_extract_variables():
    """Test variable extraction from templates."""
    engine = PromptDiffEngine()
    variables = engine.extract_variables("Hello {{name}}, welcome to {{place}}")
    
    assert "name" in variables
    assert "place" in variables


def test_prompt_diff_engine_diff_with_variables():
    """Test diff with variable analysis."""
    engine = PromptDiffEngine()
    result = engine.diff_with_variables(
        "Hello {{name}}",
        "Hello {{name}}, welcome to {{place}}"
    )
    
    assert "diff" in result
    assert "variables" in result
    assert "added" in result["variables"]
    assert "removed" in result["variables"]


def test_prompt_diff_engine_variable_changes():
    """Test variable change detection."""
    engine = PromptDiffEngine()
    result = engine.diff_with_variables(
        "Hello {{name}}",
        "Hello {{user}}"
    )
    
    assert "name" in result["variables"]["removed"]
    assert "user" in result["variables"]["added"]


def test_diff_result_summary():
    """Test diff result summary generation."""
    engine = DiffEngine(token_type="word")
    result = engine.diff("Hello", "Hello world")
    
    summary = result.get_diff_summary()
    assert "addition" in summary.lower() or "no changes" in summary.lower()
