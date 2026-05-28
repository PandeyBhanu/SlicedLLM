import re
from typing import Optional, Tuple
from pydantic import BaseModel, Field, field_validator


class SemanticVersion(BaseModel):
    """Semantic version with validation and comparison capabilities."""
    
    major: int = Field(..., ge=0, description="Major version for incompatible API changes")
    minor: int = Field(..., ge=0, description="Minor version for backwards-compatible functionality")
    patch: int = Field(..., ge=0, description="Patch version for backwards-compatible bug fixes")
    
    @classmethod
    def from_string(cls, version_string: str) -> "SemanticVersion":
        """Parse semantic version from string (e.g., '1.2.3')."""
        match = re.match(r"^(\d+)\.(\d+)\.(\d+)$", version_string)
        if not match:
            raise ValueError(f"Invalid semantic version format: {version_string}")
        
        return cls(
            major=int(match.group(1)),
            minor=int(match.group(2)),
            patch=int(match.group(3)),
        )
    
    def __str__(self) -> str:
        """Convert to string representation."""
        return f"{self.major}.{self.minor}.{self.patch}"
    
    def __lt__(self, other: "SemanticVersion") -> bool:
        """Compare versions for less than."""
        if self.major != other.major:
            return self.major < other.major
        if self.minor != other.minor:
            return self.minor < other.minor
        return self.patch < other.patch
    
    def __le__(self, other: "SemanticVersion") -> bool:
        """Compare versions for less than or equal."""
        return self < other or self == other
    
    def __gt__(self, other: "SemanticVersion") -> bool:
        """Compare versions for greater than."""
        return not self <= other
    
    def __ge__(self, other: "SemanticVersion") -> bool:
        """Compare versions for greater than or equal."""
        return not self < other
    
    def __eq__(self, other: object) -> bool:
        """Compare versions for equality."""
        if not isinstance(other, SemanticVersion):
            return False
        return (
            self.major == other.major
            and self.minor == other.minor
            and self.patch == other.patch
        )
    
    def __hash__(self) -> int:
        """Hash for use in sets and dicts."""
        return hash((self.major, self.minor, self.patch))
    
    def increment_major(self) -> "SemanticVersion":
        """Increment major version and reset minor/patch."""
        return SemanticVersion(major=self.major + 1, minor=0, patch=0)
    
    def increment_minor(self) -> "SemanticVersion":
        """Increment minor version and reset patch."""
        return SemanticVersion(major=self.major, minor=self.minor + 1, patch=0)
    
    def increment_patch(self) -> "SemanticVersion":
        """Increment patch version."""
        return SemanticVersion(major=self.major, minor=self.minor, patch=self.patch + 1)
    
    def is_compatible_with(self, other: "SemanticVersion") -> bool:
        """Check if this version is compatible with another (same major version)."""
        return self.major == other.major
    
    def get_version_difference(self, other: "SemanticVersion") -> str:
        """Get a string describing the version difference."""
        if self == other:
            return "same"
        if self.major != other.major:
            return "major"
        if self.minor != other.minor:
            return "minor"
        return "patch"


class VersionRange(BaseModel):
    """Represents a range of semantic versions."""
    
    min_version: Optional[SemanticVersion] = Field(default=None, description="Minimum version (inclusive)")
    max_version: Optional[SemanticVersion] = Field(default=None, description="Maximum version (inclusive)")
    
    def includes(self, version: SemanticVersion) -> bool:
        """Check if a version is within this range."""
        if self.min_version and version < self.min_version:
            return False
        if self.max_version and version > self.max_version:
            return False
        return True
    
    @classmethod
    def from_string(cls, range_string: str) -> "VersionRange":
        """Parse version range from string (e.g., '>=1.0.0,<2.0.0')."""
        min_version = None
        max_version = None
        
        parts = range_string.split(",")
        for part in parts:
            part = part.strip()
            if part.startswith(">="):
                min_version = SemanticVersion.from_string(part[2:])
            elif part.startswith("<="):
                max_version = SemanticVersion.from_string(part[2:])
            elif part.startswith(">"):
                min_version = SemanticVersion.from_string(part[1:])
            elif part.startswith("<"):
                max_version = SemanticVersion.from_string(part[1:])
        
        return cls(min_version=min_version, max_version=max_version)


def validate_semantic_version(version_string: str) -> Tuple[bool, Optional[str]]:
    """Validate a semantic version string.
    
    Returns:
        Tuple of (is_valid, error_message)
    """
    try:
        SemanticVersion.from_string(version_string)
        return True, None
    except ValueError as e:
        return False, str(e)


def suggest_next_version(
    current_version: str,
    change_type: str = "patch",
) -> str:
    """Suggest the next semantic version based on change type.
    
    Args:
        current_version: Current version string
        change_type: Type of change ('major', 'minor', or 'patch')
        
    Returns:
        Suggested next version string
    """
    version = SemanticVersion.from_string(current_version)
    
    if change_type == "major":
        next_version = version.increment_major()
    elif change_type == "minor":
        next_version = version.increment_minor()
    else:  # patch
        next_version = version.increment_patch()
    
    return str(next_version)
