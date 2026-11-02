#!/usr/bin/env python3
"""Conservative Rust public API inventory without executing SDK code.

Public root modules and root reexports define reachability. Public Client impl
methods remain reachable even when implemented in private client submodules.
Types and methods are intentionally inventoried separately, so a new method on
an existing exported type cannot disappear behind a preexisting class entry.
"""

from __future__ import annotations

import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def mask_literals(source: str) -> str:
    # Preserve offsets and braces outside comments/strings. Lifetime annotations
    # are not character literals and must remain visible to the impl scanner.
    pattern = re.compile(
        r'//[^\n]*|/\*[\s\S]*?\*/|(?:br|r)(?P<hash>\#*)"[\s\S]*?"(?P=hash)|b?"(?:\\.|[^"\\])*"|b?\'(?:\\.|[^\'\\\n])\''
    )
    return pattern.sub(lambda match: re.sub(r"[^\n]", " ", match.group()), source)


def brace_end(source: str, start: int) -> int:
    depth = 0
    for index in range(start, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return index
    raise ValueError("Unbalanced Rust source inventory")


def delimiter_pairs(source: str) -> dict[int, int]:
    """Validate all structural delimiters before hiding any conditional source."""
    stack = []
    pairs = {}
    for index, char in enumerate(source):
        if char in "({[":
            stack.append((char, index))
        elif char in ")}]":
            if not stack or stack[-1][0] != {")": "(", "}": "{", "]": "["}[char]:
                raise ValueError("Unbalanced Rust source inventory")
            _, opening = stack.pop()
            pairs[opening] = index
    if stack:
        raise ValueError("Unbalanced Rust source inventory")
    return pairs


def conditional_end(source: str, start: int, pairs: dict[int, int]) -> int:
    """Bound a cfg(test) member without crossing its enclosing item.

    This is deliberately a small recognizer, not a Rust parser. Unsupported or
    ambiguous attributed syntax must refuse inventory rather than hide real API.
    Offsets refer to already masked literals/comments and validated delimiters.
    """
    index = start
    while True:
        while index < len(source) and source[index].isspace():
            index += 1
        if source.startswith("#", index):
            attribute = re.match(r"#\s*\[", source[index:])
            if not attribute:
                raise ValueError("Unsupported cfg(test) attribute in Rust inventory")
            index = pairs[index + attribute.end() - 1] + 1
        else:
            break
    # A cfg(test) statement may be an explicitly balanced bare block, as in
    # the negative-only owned-socket close scheduling gate. Mask only that
    # exact block; adjacent production items remain independently inventoried.
    if index < len(source) and source[index] == "{":
        end = pairs[index] + 1
        if re.match(r"\s*else\b", source[end:]):
            raise ValueError("Unsupported cfg(test) else in Rust inventory")
        return end
    declaration = source[index:]
    visibility = r"(?:pub(?:\s*\([^)]*\))?\s+)?"
    field = re.match(visibility + r"(?:r#)?[A-Za-z_]\w*\s*:(?!:)", declaration)
    if field:
        index += field.end()
        angles = 0
        while index < len(source):
            char = source[index]
            if char in "([{":
                index = pairs[index] + 1
                continue
            if char == "<":
                angles += 1
            elif char == ">" and (index == 0 or source[index - 1] != "-"):
                if not angles:
                    raise ValueError("Ambiguous cfg(test) field in Rust inventory")
                angles -= 1
            elif char == "," and not angles:
                return index + 1
            elif char in "};)]":
                if char == "}" and not angles:
                    return index
                raise ValueError("Unterminated cfg(test) field in Rust inventory")
            elif char == "|" or re.match(r"pub\b", source[index:]):
                raise ValueError("Ambiguous cfg(test) field in Rust inventory")
            index += 1
        raise ValueError("Unterminated cfg(test) field in Rust inventory")

    item = re.match(
        visibility + r"(?:(?:async|unsafe|default|const(?=\s+fn))\s+)*(mod|fn|impl|struct|enum|trait|type|const|static|use|extern|if)\b",
        declaration,
    )
    if not item:
        raise ValueError("Unsupported cfg(test) target in Rust inventory")
    keyword = item.group(1)
    index += item.end()
    semicolon_item = keyword in {"type", "const", "static", "use"}
    if keyword == "if":
        # Only the existing simple probe binding and the actual indexed Option
        # test-observer predicate are recognized. Delimiter pairs below bound
        # the body; unknown conditions/else never hide surrounding public API.
        simple_binding = re.match(
            r"if\s+let\s+\w+\([^{}]*\)\s*=\s*&?[\w.]+\s*\{", declaration
        )
        indexed_option = re.match(
            r"if\s+[A-Za-z_]\w*\s*\[\s*[A-Za-z_]\w*\s*\]"
            r"\s*\.\s*is_some\s*\(\s*\)\s*\{", declaration
        )
        if not (simple_binding or indexed_option):
            raise ValueError("Unsupported cfg(test) condition in Rust inventory")
    angles = 0
    while index < len(source):
        char = source[index]
        if re.match(r"pub\b", source[index:]):
            raise ValueError("Unterminated cfg(test) item in Rust inventory")
        if char == "<":
            angles += 1
        elif char == ">" and (index == 0 or source[index - 1] != "-") and angles:
            angles -= 1
        if char == ";":
            if angles:
                raise ValueError("Unterminated cfg(test) generics in Rust inventory")
            return index + 1
        if char in "([{":
            end = pairs[index] + 1
            if char == "{" and angles:
                raise ValueError("Unsupported cfg(test) const generic in Rust inventory")
            if char == "{" and not semicolon_item:
                if re.match(r"\s*else\b", source[end:]):
                    raise ValueError("Unsupported cfg(test) else in Rust inventory")
                return end
            index = end
            continue
        if char in "})]":
            raise ValueError("Unterminated cfg(test) item in Rust inventory")
        index += 1
    raise ValueError("Unterminated cfg(test) item in Rust inventory")


def remove_tests(source: str) -> str:
    masked = mask_literals(source)
    pairs = delimiter_pairs(masked)
    ranges = []
    for match in re.finditer(r"#\s*\[\s*cfg\s*\(\s*test\s*\)\s*\]", masked):
        if ranges and match.start() < ranges[-1][1]:
            continue
        ranges.append((match.start(), conditional_end(masked, match.end(), pairs)))
    for start, end in reversed(ranges):
        masked = masked[:start] + re.sub(r"[^\n]", " ", masked[start:end]) + masked[end:]
    return masked


def discover(root: Path = ROOT) -> list[str]:
    source_root = root / "packages/openmates-rust/src"
    library = remove_tests((source_root / "lib.rs").read_text())
    public_modules = set(re.findall(r"\bpub\s+mod\s+(\w+)\s*;", library))
    symbols = set(public_modules)
    wildcard_exports = []
    reexported_modules = set()
    for exported in re.finditer(r"\bpub\s+use\s+([^;]+);", library):
        expression = exported.group(1).strip()
        if "::" in expression:
            reexported_modules.add(expression.split("::", 1)[0])
        if expression.endswith("::*"):
            wildcard_exports.append(expression[:-3].replace("::", "."))
            continue
        entries = (
            expression.split("{", 1)[1].rsplit("}", 1)[0].split(",")
            if "{" in expression
            else [expression]
        )
        for entry in entries:
            name = entry.strip().rsplit(" as ", 1)[-1].rsplit("::", 1)[-1].strip()
            if re.fullmatch(r"[A-Za-z_]\w*", name):
                symbols.add(name)
    for file in sorted(source_root.rglob("*.rs")):
        relative = file.relative_to(source_root)
        module = relative.parts[0].removesuffix(".rs")
        only_client_extensions = (
            module not in public_modules | reexported_modules and module != "lib"
        )
        source = remove_tests(file.read_text())
        namespace = ".".join(relative.with_suffix("").parts)
        if module == "lib":
            namespace = ""
        if namespace.endswith(".mod"):
            namespace = namespace[:-4]
        implementations = []
        for declaration in re.finditer(r"\bimpl\b([^;{]+)\{", source):
            header = declaration.group(1).split(" for ")[-1].strip()
            if header.startswith("<"):
                depth = 0
                for index, char in enumerate(header):
                    depth += (char == "<") - (char == ">")
                    if depth == 0:
                        header = header[index + 1 :].strip()
                        break
            identity = re.match(r"(?:(?:\w+)::)*([A-Za-z_]\w*)", header)
            if identity:
                implementations.append(
                    (
                        declaration.end() - 1,
                        brace_end(source, declaration.end() - 1),
                        identity.group(1),
                    )
                )
        for declaration in re.finditer(
            r"\bpub\s+(?:(?:async|const|unsafe)\s+)*fn\s+((?:r#)?\w+)\s*[(<]", source
        ):
            implementation = next(
                (
                    owner
                    for start, end, owner in reversed(implementations)
                    if start < declaration.start() < end
                ),
                None,
            )
            if only_client_extensions and implementation != "Client":
                continue
            # Client extensions in private submodules are public on Client.
            prefix = (
                "client.Client"
                if implementation == "Client"
                else f"{namespace}.{implementation}"
                if implementation
                else namespace
            )
            symbols.add(prefix + "." + declaration.group(1))
        if only_client_extensions:
            continue
        for declaration in re.finditer(
            r"\bpub\s+(?:struct|enum|trait|type|const|static)\s+(\w+)", source
        ):
            symbols.add(namespace + "." + declaration.group(1))
        for declaration in re.finditer(r"\bpub\s+struct\s+(\w+)[^;{]*\{", source):
            body = source[declaration.end() : brace_end(source, declaration.end() - 1)]
            for field in re.finditer(r"\bpub\s+((?:r#)?\w+)\s*:", body):
                symbols.add(f"{namespace}.{declaration.group(1)}.{field.group(1)}")
        # Trait members are public without a `pub` modifier in their body.
        for declaration in re.finditer(r"\bpub\s+trait\s+(\w+)[^{]*\{", source):
            body = source[declaration.end() : brace_end(source, declaration.end() - 1)]
            for member in re.finditer(r"\b(?:fn|type|const)\s+((?:r#)?\w+)", body):
                symbols.add(f"{namespace}.{declaration.group(1)}.{member.group(1)}")
        for declaration in re.finditer(r"\bpub\s+enum\s+(\w+)[^;{]*\{", source):
            body = source[declaration.end() : brace_end(source, declaration.end() - 1)]
            level = start = 0
            for index, character in enumerate(body + ","):
                if character in "{([<":
                    level += 1
                elif character in "})]>":
                    level -= 1
                elif character == "," and level == 0:
                    variant = re.match(r"\s*([A-Za-z_]\w*)", body[start:index])
                    if variant:
                        symbols.add(
                            f"{namespace}.{declaration.group(1)}.{variant.group(1)}"
                        )
                    start = index + 1
    for module in wildcard_exports:
        symbols.update(
            name.removeprefix(module + ".")
            for name in list(symbols)
            if name.startswith(module + ".")
            and "." not in name.removeprefix(module + ".")
        )
    return sorted(name.lstrip(".") for name in symbols)


if __name__ == "__main__":
    print(json.dumps(discover()))
