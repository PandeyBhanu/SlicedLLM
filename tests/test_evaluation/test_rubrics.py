import pytest
from app.evaluation.rubrics import ContentCheck, FormatCheck, GroundingCheck, ToneCheck


@pytest.mark.asyncio
async def test_format_check_pass():
    """Test FormatCheck with passing criteria."""
    rubric = FormatCheck()
    
    result = await rubric.evaluate(
        generated_text='{"name": "test", "value": 123}',
        expected_behavior={"format": "json"},
    )
    
    assert result.passed is True
    assert result.confidence_score > 0.8


@pytest.mark.asyncio
async def test_format_check_fail():
    """Test FormatCheck with failing criteria."""
    rubric = FormatCheck()
    
    result = await rubric.evaluate(
        generated_text='Not valid JSON',
        expected_behavior={"format": "json"},
    )
    
    assert result.passed is False
    assert result.confidence_score < 0.6


@pytest.mark.asyncio
async def test_format_check_length_constraints():
    """Test FormatCheck with length constraints."""
    rubric = FormatCheck()
    
    result = await rubric.evaluate(
        generated_text="Short",
        expected_behavior={"min_length": 10},
    )
    
    assert result.passed is False


@pytest.mark.asyncio
async def test_content_check_pass():
    """Test ContentCheck with passing criteria."""
    rubric = ContentCheck()
    
    result = await rubric.evaluate(
        generated_text="The quick brown fox jumps over the lazy dog",
        expected_behavior={"keywords": ["quick", "fox", "dog"]},
    )
    
    assert result.passed is True
    assert result.confidence_score > 0.8


@pytest.mark.asyncio
async def test_content_check_fail():
    """Test ContentCheck with failing criteria."""
    rubric = ContentCheck()
    
    result = await rubric.evaluate(
        generated_text="The cat sat on the mat",
        expected_behavior={"keywords": ["quick", "fox", "dog"]},
    )
    
    assert result.passed is False
    assert result.confidence_score < 0.5


@pytest.mark.asyncio
async def test_content_check_excluded_keywords():
    """Test ContentCheck with excluded keywords."""
    rubric = ContentCheck()
    
    result = await rubric.evaluate(
        generated_text="This is terrible and awful",
        expected_behavior={"excluded_keywords": ["terrible", "awful"]},
    )
    
    assert result.passed is False


@pytest.mark.asyncio
async def test_tone_check_professional():
    """Test ToneCheck for professional tone."""
    rubric = ToneCheck()
    
    result = await rubric.evaluate(
        generated_text="Thank you for your inquiry. We appreciate your business.",
        expected_behavior={"tone": "professional"},
    )
    
    assert result.passed is True


@pytest.mark.asyncio
async def test_tone_check_casual():
    """Test ToneCheck for casual tone."""
    rubric = ToneCheck()
    
    result = await rubric.evaluate(
        generated_text="Hey! What's up? This is cool stuff!",
        expected_behavior={"tone": "casual"},
    )
    
    assert result.passed is True


@pytest.mark.asyncio
async def test_tone_check_sentiment_positive():
    """Test ToneCheck for positive sentiment."""
    rubric = ToneCheck()
    
    result = await rubric.evaluate(
        generated_text="This is excellent and wonderful!",
        expected_behavior={"sentiment": "positive"},
    )
    
    assert result.passed is True


@pytest.mark.asyncio
async def test_tone_check_sentiment_negative():
    """Test ToneCheck for negative sentiment."""
    rubric = ToneCheck()
    
    result = await rubric.evaluate(
        generated_text="This is terrible and awful",
        expected_behavior={"sentiment": "negative"},
    )
    
    assert result.passed is True


@pytest.mark.asyncio
async def test_grounding_check_pass():
    """Test GroundingCheck with proper grounding."""
    rubric = GroundingCheck()
    
    result = await rubric.evaluate(
        generated_text="According to the document, the value is 42",
        expected_behavior={"required_sources": ["document"]},
        context={"source_context": "The document states the value is 42"},
    )
    
    assert result.passed is True


@pytest.mark.asyncio
async def test_grounding_check_fail():
    """Test GroundingCheck with missing sources."""
    rubric = GroundingCheck()
    
    result = await rubric.evaluate(
        generated_text="The value is 42",
        expected_behavior={"required_sources": ["document"]},
    )
    
    assert result.passed is False


@pytest.mark.asyncio
async def test_grounding_check_forbidden_claims():
    """Test GroundingCheck with forbidden claims."""
    rubric = GroundingCheck()
    
    result = await rubric.evaluate(
        generated_text="The system can predict the future",
        expected_behavior={"forbidden_claims": ["predict the future"]},
    )
    
    assert result.passed is False


@pytest.mark.asyncio
async def test_rubric_description():
    """Test that rubrics provide descriptions."""
    rubrics = [FormatCheck(), ContentCheck(), ToneCheck(), GroundingCheck()]
    
    for rubric in rubrics:
        description = rubric.get_description()
        assert isinstance(description, str)
        assert len(description) > 0
