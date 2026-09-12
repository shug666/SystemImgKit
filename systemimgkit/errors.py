"""Shared exception types for SystemImgKit."""


class SystemImgKitError(Exception):
    """Base class for all tool errors."""


class UnsupportedImageError(SystemImgKitError):
    """The input image format is not supported (e.g. sparse, EROFS)."""


class AvbFooterError(SystemImgKitError):
    """The AVB footer is missing, malformed, or fails validation."""


class MissingDependencyError(SystemImgKitError):
    """A required external tool (debugfs, mke2fs, …) is not installed."""


class InsufficientSpaceError(SystemImgKitError):
    """The workspace does not have enough free space for the operation."""


class GuardViolationError(SystemImgKitError):
    """An attempt was made to delete a guarded/protected path."""


class ValidationFailedError(SystemImgKitError):
    """e2fsck reported uncorrectable errors on the rebuilt image."""


class SizeCapExceededError(SystemImgKitError):
    """The edited tree would produce an image larger than the partition."""
