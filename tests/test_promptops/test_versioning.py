import pytest

from app.promptops.versioning import (
    SemanticVersion,
    VersionRange,
    suggest_next_version,
    validate_semantic_version,
)


def test_semantic_version_from_string():
    """Test parsing semantic version from string."""
    version = SemanticVersion.from_string("1.2.3")
    assert version.major == 1
    assert version.minor == 2
    assert version.patch == 3


def test_semantic_version_from_string_invalid():
    """Test parsing invalid semantic version string."""
    with pytest.raises(ValueError):
        SemanticVersion.from_string("invalid")

    with pytest.raises(ValueError):
        SemanticVersion.from_string("1.2")

    with pytest.raises(ValueError):
        SemanticVersion.from_string("1.2.3.4")


def test_semantic_version_to_string():
    """Test converting semantic version to string."""
    version = SemanticVersion(major=1, minor=2, patch=3)
    assert str(version) == "1.2.3"


def test_semantic_version_comparison():
    """Test semantic version comparison operators."""
    v1 = SemanticVersion.from_string("1.2.3")
    v2 = SemanticVersion.from_string("1.2.4")
    v3 = SemanticVersion.from_string("2.0.0")

    assert v1 < v2
    assert v2 > v1
    assert v1 <= v2
    assert v2 >= v1
    assert v1 == SemanticVersion.from_string("1.2.3")
    assert v1 != v2
    assert v2 < v3


def test_semantic_version_increment_major():
    """Test incrementing major version."""
    version = SemanticVersion.from_string("1.2.3")
    next_version = version.increment_major()
    assert next_version.major == 2
    assert next_version.minor == 0
    assert next_version.patch == 0


def test_semantic_version_increment_minor():
    """Test incrementing minor version."""
    version = SemanticVersion.from_string("1.2.3")
    next_version = version.increment_minor()
    assert next_version.major == 1
    assert next_version.minor == 3
    assert next_version.patch == 0


def test_semantic_version_increment_patch():
    """Test incrementing patch version."""
    version = SemanticVersion.from_string("1.2.3")
    next_version = version.increment_patch()
    assert next_version.major == 1
    assert next_version.minor == 2
    assert next_version.patch == 4


def test_semantic_version_compatibility():
    """Test version compatibility check."""
    v1 = SemanticVersion.from_string("1.2.3")
    v2 = SemanticVersion.from_string("1.3.0")
    v3 = SemanticVersion.from_string("2.0.0")

    assert v1.is_compatible_with(v2)
    assert not v1.is_compatible_with(v3)


def test_semantic_version_difference():
    """Test version difference description."""
    v1 = SemanticVersion.from_string("1.2.3")
    v2 = SemanticVersion.from_string("1.2.4")
    v3 = SemanticVersion.from_string("1.3.0")
    v4 = SemanticVersion.from_string("2.0.0")

    assert v1.get_version_difference(v1) == "same"
    assert v1.get_version_difference(v2) == "patch"
    assert v1.get_version_difference(v3) == "minor"
    assert v1.get_version_difference(v4) == "major"


def test_version_range_includes():
    """Test version range inclusion."""
    min_v = SemanticVersion.from_string("1.0.0")
    max_v = SemanticVersion.from_string("2.0.0")

    range_obj = VersionRange(min_version=min_v, max_version=max_v)

    assert range_obj.includes(SemanticVersion.from_string("1.5.0"))
    assert range_obj.includes(SemanticVersion.from_string("1.0.0"))
    assert range_obj.includes(SemanticVersion.from_string("2.0.0"))
    assert not range_obj.includes(SemanticVersion.from_string("0.9.0"))
    assert not range_obj.includes(SemanticVersion.from_string("2.1.0"))


def test_validate_semantic_version_valid():
    """Test validating valid semantic version."""
    is_valid, error = validate_semantic_version("1.2.3")
    assert is_valid is True
    assert error is None


def test_validate_semantic_version_invalid():
    """Test validating invalid semantic version."""
    is_valid, error = validate_semantic_version("invalid")
    assert is_valid is False
    assert error is not None


def test_suggest_next_version_patch():
    """Test suggesting next patch version."""
    suggested = suggest_next_version("1.2.3", "patch")
    assert suggested == "1.2.4"


def test_suggest_next_version_minor():
    """Test suggesting next minor version."""
    suggested = suggest_next_version("1.2.3", "minor")
    assert suggested == "1.3.0"


def test_suggest_next_version_major():
    """Test suggesting next major version."""
    suggested = suggest_next_version("1.2.3", "major")
    assert suggested == "2.0.0"


def test_suggest_next_version_first():
    """Test suggesting first version."""
    suggested = suggest_next_version("", "patch")
    assert suggested == "1.0.0"
