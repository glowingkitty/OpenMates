#!/usr/bin/env python3
"""Read-only registration preflight; does not prove route or sign-in behavior."""

import argparse
import json
import sys
from urllib.request import Request, urlopen


def missing_routes(schema, required):
    paths = schema.get("paths")
    if not isinstance(paths, dict):
        raise ValueError("OpenAPI schema has no paths object")
    return [
        (method, path) for method, path in required
        if not isinstance(paths.get(path), dict)
        or not isinstance(paths[path].get(method.lower()), dict)
    ]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--api-url")
    source.add_argument("--schema-file", help="OpenAPI snapshot from the running API")
    parser.add_argument("--require", nargs=2, action="append", required=True,
                        metavar=("METHOD", "PATH"))
    args = parser.parse_args()
    try:
        if args.schema_file:
            with open(args.schema_file, encoding="utf-8") as document:
                schema = json.load(document)
        else:
            request = Request(args.api_url.rstrip("/") + "/openapi.json",
                              headers={"Cache-Control": "no-cache", "Accept": "application/json"})
            with urlopen(request, timeout=20) as response:
                schema = json.load(response)
        missing = missing_routes(schema, args.require)
        if missing:
            for method, path in missing:
                print(f"Missing registered route: {method.upper()} {path}", file=sys.stderr)
            return 1
    except Exception as exc:
        # Do not print URLs, response bodies or exception messages containing secrets.
        print(f"Could not verify API route registration ({type(exc).__name__})", file=sys.stderr)
        return 1
    print("Required API routes are registered; behavior still needs verification.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
