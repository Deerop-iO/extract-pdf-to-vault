"""Shared, deterministic helpers for the pdf-to-vault pipeline.

These modules are pure (no PDF parsing, no I/O side effects beyond what callers
ask for) so they can be unit-tested in isolation. The kit's own tests/ exercise
this exact code.
"""
