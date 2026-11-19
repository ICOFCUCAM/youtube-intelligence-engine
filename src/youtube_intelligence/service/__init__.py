"""Stateless HTTP/JSON service over the library (`yt-serve`). ICOFCUCAM addition.

Each endpoint wraps one library function. No storage, no network calls of its own, no YouTube
writes. Inputs are JSON bodies; transcripts and CSVs are sent as CONTENT, never as file paths.
"""
