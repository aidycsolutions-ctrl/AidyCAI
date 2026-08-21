class RegistryError(Exception):
    """Base error for project registry operations."""


class DuplicateProjectError(RegistryError):
    """A project with the same id, name, or path is already registered."""


class ProjectNotFoundError(RegistryError):
    """No registered project matches the given name or id."""


class InvalidPathError(RegistryError):
    """The given path is not a usable project directory."""


class IndexingError(RegistryError):
    """Indexing or search failed for a registered project."""
