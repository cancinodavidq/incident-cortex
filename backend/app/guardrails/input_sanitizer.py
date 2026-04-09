import logging
import mimetypes
from typing import List, Optional, Tuple
from pathlib import Path

logger = logging.getLogger(__name__)

# Allowed file types for incident attachments
ALLOWED_MIME_TYPES = {
    "text/plain",
    "text/markdown",
    "text/csv",
    "application/json",
    "application/pdf",
    "application/x-yaml",
    "text/x-python",
    "text/x-shellscript",
    "text/x-log",
    "application/xml",
    "text/xml",
}

# Maximum file size: 10 MB
MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024

# Maximum total upload size: 50 MB
MAX_TOTAL_UPLOAD_BYTES = 50 * 1024 * 1024


class InputSanitizer:
    """Validates and sanitizes incident file uploads."""

    @staticmethod
    def validate_filename(filename: str) -> Tuple[bool, str]:
        """
        Validate filename for safety.
        Returns (is_valid, reason).
        """
        if not filename or len(filename) > 255:
            return False, "Filename is empty or too long"

        # Reject path traversal attempts
        if ".." in filename or "/" in filename or "\\" in filename:
            return False, "Filename contains path traversal characters"

        # Check for null bytes
        if "\x00" in filename:
            return False, "Filename contains null bytes"

        return True, ""

    @staticmethod
    def validate_file_type(filename: str, content_type: str = None) -> Tuple[bool, str]:
        """
        Validate file type based on extension and MIME type.
        Returns (is_valid, reason).
        """
        # Get MIME type from filename if not provided
        if not content_type:
            content_type, _ = mimetypes.guess_type(filename)

        if not content_type:
            return False, "Could not determine file MIME type"

        # Check against whitelist
        if content_type not in ALLOWED_MIME_TYPES:
            return False, f"File type {content_type} is not allowed"

        return True, ""

    @staticmethod
    def validate_file_size(file_size_bytes: int) -> Tuple[bool, str]:
        """
        Validate individual file size.
        Returns (is_valid, reason).
        """
        if file_size_bytes > MAX_FILE_SIZE_BYTES:
            return False, f"File exceeds maximum size of {MAX_FILE_SIZE_BYTES / 1024 / 1024:.1f} MB"

        if file_size_bytes == 0:
            return False, "File is empty"

        return True, ""

    @staticmethod
    def validate_total_upload_size(total_bytes: int) -> Tuple[bool, str]:
        """
        Validate total upload size.
        Returns (is_valid, reason).
        """
        if total_bytes > MAX_TOTAL_UPLOAD_BYTES:
            return False, (
                f"Total upload exceeds maximum size of "
                f"{MAX_TOTAL_UPLOAD_BYTES / 1024 / 1024:.1f} MB"
            )

        return True, ""

    @staticmethod
    def validate_files(files: List[Tuple[str, int, Optional[str]]]) -> Tuple[bool, str, List[str]]:
        """
        Validate a list of files.
        Input: List of (filename, file_size_bytes, content_type) tuples
        Returns (is_valid, reason, validated_filenames)
        """
        total_size = 0
        validated_names = []

        for filename, file_size, content_type in files:
            # Validate filename
            is_valid, reason = InputSanitizer.validate_filename(filename)
            if not is_valid:
                logger.warning(f"Invalid filename '{filename}': {reason}")
                return False, f"Invalid filename: {reason}", []

            # Validate file type
            is_valid, reason = InputSanitizer.validate_file_type(filename, content_type)
            if not is_valid:
                logger.warning(f"Invalid file type for '{filename}': {reason}")
                return False, f"Invalid file type: {reason}", []

            # Validate individual file size
            is_valid, reason = InputSanitizer.validate_file_size(file_size)
            if not is_valid:
                logger.warning(f"File size violation for '{filename}': {reason}")
                return False, f"File size error: {reason}", []

            total_size += file_size
            validated_names.append(filename)

        # Validate total upload size
        is_valid, reason = InputSanitizer.validate_total_upload_size(total_size)
        if not is_valid:
            logger.warning(f"Total upload size violation: {reason}")
            return False, reason, []

        return True, "", validated_names
