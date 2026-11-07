"""Read-only, tenant-scoped document store with group ACLs."""

from servers.docstore.server import DocStore, Document, build_server

__all__ = ["DocStore", "Document", "build_server"]
