"""
Module to handle Changelog generation for software projects.

This module provides functionality to detect Changelog files in package archives and generate
matching Changelog files in repositories using various changelog generation tools and formats.

The ChangelogRunner is invoked only if a Changelog file is detected in the package archive but
missing from the repository. The generated Changelog file matches the format and size of the
original archive Changelog.

NOTE: This implementation currently supports only generation from git log variations, but can be
extended in the future to support other changelog generation tools and formats.
"""

import logging
import re
import subprocess
from enum import Enum
from pathlib import Path
from typing import Optional, Tuple

from package_validation_tool.utils import pushd

log = logging.getLogger(__name__)

# Common changelog filename variations
CHANGELOG_VARIATIONS = [
    "ChangeLog",
    "CHANGELOG",
    "changelog",
    "ChangeLog.txt",
    "CHANGELOG.txt",
    "changelog.txt",
    "ChangeLog.md",
    "CHANGELOG.md",
    "changelog.md",
    "CHANGES",
    "changes",
    "CHANGES.txt",
    "changes.txt",
    "HISTORY",
    "history",
    "HISTORY.txt",
    "history.txt",
    "NEWS",
    "news",
    "NEWS.txt",
    "news.txt",
]


class ChangelogGenerator(Enum):
    """
    Enum representing different changelog generation tools and formats.

    Values:
        Unknown: Format not recognized or not supported
        GitLog: Changelog generated using git log command with various formatting options
    """

    Unknown = "unknown"
    GitLog = "git_log"


class ChangelogRunner:
    """
    Changelog automation runner for software projects.

    This class handles the detection of Changelog files in package archives and generates matching
    Changelog files in repositories using various changelog generation tools. The implementation
    can be extended to support different changelog formats and generators. Currently supports git
    log variations with appropriate formatting and truncation to match the original size.
    """

    def __init__(self, src_repo_dir: str, package_archive_dir: str):
        """
        Initialize the ChangelogRunner.

        Args:
            src_repo_dir: Directory containing the source code repository
            package_archive_dir: Directory containing the changelog-containing package archive
        """
        self.src_repo_dir = Path(src_repo_dir).resolve()
        self.package_archive_dir = Path(package_archive_dir).resolve()

        log.debug("ChangelogRunner initialized with:")
        log.debug("  src_repo_dir: %s", self.src_repo_dir)
        log.debug("  package_archive_dir: %s", self.package_archive_dir)

    def run_changelog_generation(self) -> bool:
        """
        Main method to run all Changelog generation steps.

        This method executes the complete Changelog workflow:
        1. Check if Changelog exists in source repository
        2. Find Changelog in package archive
        3. Analyze the archive Changelog format to determine the appropriate generator
        4. Generate matching Changelog using the detected generator
        5. Truncate to match original size

        Returns:
            bool: True if generation completed successfully, False otherwise
        """
        log.info("Starting Changelog processing...")

        # Check if changelog already exists in source repo
        src_changelog_path = self._find_changelog_in_dir(self.src_repo_dir)
        if src_changelog_path:
            log.info("Changelog already exists in source repository: %s", src_changelog_path.name)
            return True

        # Find changelog in package archive
        archive_changelog_path = self._find_changelog_in_dir(self.package_archive_dir)
        if not archive_changelog_path:
            log.info("No Changelog file found in package archive, nothing to do")
            return True

        log.info("Found Changelog in package archive: %s", archive_changelog_path.name)

        # Analyze the format of the archive changelog
        generator, additional_args = self._analyze_changelog_format(archive_changelog_path)
        if generator == ChangelogGenerator.Unknown:
            log.info("Could not determine changelog generator from archive changelog format")
            return False

        log.info("Detected changelog generator: %s with args: %s", generator.value, additional_args)

        # Get the target file size
        target_size = archive_changelog_path.stat().st_size

        # Generate the changelog using the appropriate generator
        target_changelog_path = self.src_repo_dir / archive_changelog_path.name
        if generator == ChangelogGenerator.GitLog:
            if not self._generate_changelog_using_gitlog(target_changelog_path, additional_args):
                log.error("Failed to generate changelog file using git log")
                return False
        else:
            # This should not happen given current implementation, but future-proofing
            log.error("Unsupported changelog generator: %s", generator)
            return False

        # Truncate the changelog to match target size
        if not self._truncate_changelog_file(target_changelog_path, target_size):
            log.error("Failed to truncate changelog file")
            return False

        log.info("Changelog processing completed successfully")
        return True

    def _find_changelog_in_dir(self, directory: Path) -> Optional[Path]:
        """
        Find a changelog file in the given directory.

        Args:
            directory: Directory to search for changelog files

        Returns:
            Path to the found changelog file, or None if not found
        """
        log.debug("Searching for changelog files in %s", directory)

        for filename in CHANGELOG_VARIATIONS:
            filepath = directory / filename
            if filepath.is_file():
                log.debug("Found changelog file: %s", filename)
                return filepath

        log.debug("No changelog file found in %s", directory)
        return None

    def _analyze_changelog_format(
        self, changelog_path: Path
    ) -> Tuple[ChangelogGenerator, Optional[str]]:
        """
        Analyze the changelog format to determine appropriate changelog generator and parameters.

        This method uses heuristics to detect the format used in the changelog and determines
        which generator should be used along with any additional parameters needed.

        Args:
            changelog_path: Path to the changelog file to analyze

        Returns:
            Tuple of (ChangelogGenerator, additional_parameters):
            - ChangelogGenerator: The detected generator type
            - additional_parameters: Generator-specific parameters, or None if format not recognized
        """
        log.debug("Analyzing changelog format from %s", changelog_path)

        try:
            # Read first 20 lines to analyze format
            with open(changelog_path, "r", encoding="utf-8", errors="ignore") as f:
                sample_lines = []
                for i, line in enumerate(f):
                    if i >= 20:
                        break
                    sample_lines.append(line.strip())
        except Exception as e:
            log.error("Error reading changelog file %s: %r", changelog_path, e)
            return ChangelogGenerator.Unknown, None

        sample_text = "\n".join(sample_lines)

        # Heuristic 1: Look for full commit hash (40 hex chars) and specific git log formats
        if re.search(r"\b[a-f0-9]{40}\b", sample_text):
            log.debug("Detected full commit hashes")

            # Check for oneline format: hash followed by subject on same line
            if re.search(r"^[a-f0-9]{40}\s+\S", sample_text, re.MULTILINE):
                log.debug("Detected oneline format")
                return ChangelogGenerator.GitLog, "--pretty=oneline"

            # Check for full format: has "Commit:" field
            if re.search(r"commit [a-f0-9]{40}.*\nAuthor:.*\nCommit:", sample_text):
                log.debug("Detected full format")
                return ChangelogGenerator.GitLog, "--pretty=full"

            # Check for medium format: has "Date:" field but no "Commit:" field
            if re.search(r"commit [a-f0-9]{40}.*\nAuthor:.*\nDate:", sample_text):
                log.debug("Detected medium format")
                return ChangelogGenerator.GitLog, "--pretty=medium"

            # Check for short format: has "Author:" but no "Date:" or "Commit:" field
            if re.search(r"commit [a-f0-9]{40}.*\nAuthor:", sample_text):
                log.debug("Detected short format")
                return ChangelogGenerator.GitLog, "--pretty=short"

        # Heuristic 2: Look for abbreviated commit hash (7-12 hex characters)
        if re.search(r"\b[a-f0-9]{7,12}\b", sample_text):
            log.debug("Detected abbreviated commit hashes")
            return ChangelogGenerator.GitLog, "--pretty=format:%h %s"

        # If no git log patterns are detected, return Unknown
        log.debug("Could not recognize changelog format")
        return ChangelogGenerator.Unknown, None

    def _generate_changelog_using_gitlog(self, target_path: Path, git_log_format: str) -> bool:
        """
        Generate a changelog file using git log with the specified format.

        Args:
            target_path: Path where the changelog file should be created
            git_log_format: Git log format string to use

        Returns:
            bool: True if generation succeeded, False otherwise
        """
        log.debug(
            "Generating changelog file %s with git log format %s", target_path, git_log_format
        )

        try:
            with pushd(str(self.src_repo_dir)):
                cmd = ["git", "log", "--no-decorate"]
                if git_log_format:  # Only append if not empty string
                    cmd.append(git_log_format)

                log.debug("Running command: %s", " ".join(cmd))
                result = subprocess.run(cmd, capture_output=True, text=True, check=False)

                if result.returncode != 0:
                    log.error("Git log command failed: %s", result.stderr.strip())
                    return False

                changelog_content = result.stdout

                if not changelog_content:
                    log.warning("Git log produced no output")
                    return False

                log.debug(
                    "Generated %d bytes of changelog content",
                    len(changelog_content.encode("utf-8")),
                )

                with open(target_path, "w", encoding="utf-8") as f:
                    f.write(changelog_content)
                return True

        except Exception as e:
            log.error("Error generating changelog file: %r", e)
            return False

    def _truncate_changelog_file(self, target_path: Path, target_size: int) -> bool:
        """
        Truncate a changelog file to the specified target size.

        Args:
            target_path: Path to the changelog file to truncate
            target_size: Target size in bytes for the truncated file

        Returns:
            bool: True if truncation succeeded, False otherwise
        """
        log.debug("Truncating changelog file %s to %d bytes", target_path, target_size)

        try:
            with open(target_path, "r+", encoding="utf-8") as f:
                f.truncate(target_size)
            return True

        except Exception as e:
            log.error("Error truncating changelog file: %r", e)
            return False
