def test_backend_modules_import_without_network():
    from app import chat, criterion, pointers  # noqa: F401
