"""OpenAPI 3.1 description of yt-serve, served at GET /v1/openapi.json.

Hand-written to describe the request fields precisely; ``tests/test_service.py`` fails if a route
exists in the server but not here, or the reverse.
"""
from __future__ import annotations

from typing import Dict

from .. import __version__

S = {"type": "string"}
N = {"type": "number"}
I = {"type": "integer"}
B = {"type": "boolean"}
OBJ = {"type": "object"}
TRANSCRIPT = {
    "oneOf": [
        {"type": "object", "required": ["format", "content"], "additionalProperties": False,
         "properties": {"format": {"enum": ["srt", "vtt", "json"]}, "content": S}},
        {"type": "object", "required": ["cues"], "additionalProperties": False,
         "properties": {"cues": {"type": "array", "maxItems": 100000, "items": {
             "type": "object", "required": ["start", "end"],
             "properties": {"start": N, "end": N, "text": S}}}}},
    ],
    "description": "Transcript CONTENT. No endpoint accepts a file path.",
}


def _body(required, props) -> Dict:
    return {"required": True, "content": {"application/json": {"schema": {
        "type": "object", "required": list(required), "properties": props}}}}


def _op(summary, required=(), props=None, desc=None) -> Dict:
    op = {"summary": summary, "responses": {
        "200": {"description": "OK", "content": {"application/json": {"schema": OBJ}}},
        "400": {"$ref": "#/components/responses/Error"},
        "401": {"$ref": "#/components/responses/Error"},
        "413": {"$ref": "#/components/responses/Error"},
        "415": {"$ref": "#/components/responses/Error"}}}
    if props is not None:
        op["requestBody"] = _body(required, props)
    if desc:
        op["description"] = desc
    return {"post": op}


def spec() -> Dict:
    paths = {
        "/v1/health": {"get": {"summary": "Liveness and version", "security": [],
                               "responses": {"200": {"description": "OK"}}}},
        "/v1/openapi.json": {"get": {"summary": "This document", "security": [],
                                     "responses": {"200": {"description": "OK"}}}},
        "/v1/edl": _op("Edit decision list (edl@1) from a transcript", ["transcript"], {
            "transcript": TRANSCRIPT, "floor": N, "words": {"enum": ["auto", "off"]},
            "review_below": N, "hold_review": B}),
        "/v1/chapters": _op("YouTube chapters, validated against YouTube's rules", ["transcript"],
                            {"transcript": TRANSCRIPT, "target": I}),
        "/v1/hooks/score": _op("Heuristic hook score (not a prediction of views)", ["hooks"],
                               {"hooks": {"type": "array", "items": S, "minItems": 1, "maxItems": 500}}),
        "/v1/titles/check": _op("Title and thumbnail-text lint", ["titles"],
                                {"titles": {"type": "array", "items": S, "minItems": 1, "maxItems": 500}, "thumb": S}),
        "/v1/retention": _op("Audience-retention reading (hook leak, cliffs, slide)", [], {
            "csv": S, "rows": {"type": "array", "items": {"type": "array", "items": N, "minItems": 2, "maxItems": 2}},
            "duration": N, "axis": {"enum": ["auto", "percent", "seconds"]}, "views": I, "transcript": TRANSCRIPT},
            "Send exactly one of `csv` (YouTube Studio export text) or `rows`."),
        "/v1/outliers": _op("Videos ranked by multiple over their own channel's median", ["videos"],
                            {"videos": {"type": "array", "maxItems": 20000, "items": OBJ}, "min": N}),
        "/v1/shorts": _op("Candidate Shorts spans", ["transcript"],
                          {"transcript": TRANSCRIPT, "min": N, "max": N, "top": I}),
        "/v1/handoff/approve": _op("Approval record pinning artefacts by SHA-256 (signed when the server has a key)",
                                   ["approved_by"], {"approved_by": S, "edl": OBJ, "chapters": OBJ, "shorts": OBJ,
                                                     "picked_shorts": {"type": "array", "items": I},
                                                     "acknowledge_review": B},
                                   "`approved_by` is asserted by the caller; authenticate the person before calling."),
        "/v1/handoff/instruction": _op("production-instruction@1 from approved artefacts", ["approval", "media"], {
            "approval": OBJ, "media": S, "edl": OBJ, "chapters": OBJ, "shorts": OBJ, "transcript_offset": N,
            "aspect": {"enum": ["9:16", "16:9", "1:1"]}, "project": {"type": "object", "additionalProperties": S}},
            "Every artefact must match its approved hash. Schema: docs/schemas/production-instruction-1.schema.json"),
        "/v1/handoff/validate": _op("Validate a production instruction", ["instruction"], {"instruction": OBJ}),
    }
    return {
        "openapi": "3.1.0",
        "info": {"title": "YouTube Intelligence Engine", "version": __version__,
                 "description": "Stateless analysis API. Never writes to YouTube. Inputs are content, never file paths.",
                 "license": {"name": "MIT"}},
        "servers": [{"url": "http://127.0.0.1:8765"}],
        "security": [{"bearer": []}],
        "paths": paths,
        "components": {
            "securitySchemes": {"bearer": {"type": "http", "scheme": "bearer",
                                           "description": "Required on POST when the server has YIE_API_TOKEN."}},
            "schemas": {"Error": {"type": "object", "required": ["error"], "properties": {"error": {
                "type": "object", "required": ["code", "message"], "properties": {"code": S, "message": S}}}}},
            "responses": {"Error": {"description": "Error", "content": {"application/json": {
                "schema": {"$ref": "#/components/schemas/Error"}}}}},
        },
    }
