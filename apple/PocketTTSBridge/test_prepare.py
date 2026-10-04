"""Small source-bound privacy and extraction checks; no native build or weights."""
import hashlib
import importlib.util
import io
from pathlib import Path
import tarfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("pocket_prepare", Path(__file__).with_name("prepare.py"))
prepare = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prepare)


def archive(extra=None):
    data = io.BytesIO()
    with tarfile.open(fileobj=data, mode="w:gz") as tar:
        for name, body in [("src/lib.rs", b"//! header\n#![allow(dead_code)]\npub mod audio;\n"),
                           ("Cargo.toml", b'crate-type = ["staticlib", "cdylib", "rlib"]\n')]:
            member = tarfile.TarInfo(f"pocket-tts-ios-{prepare.REVISION}/{name}")
            member.size = len(body); tar.addfile(member, io.BytesIO(body))
        if extra is not None: tar.addfile(extra)
    return data.getvalue()


class PocketPrepareTests(unittest.TestCase):
    def test_checksum_rejection_precedes_extraction(self):
        with self.assertRaisesRegex(ValueError, "checksum"):
            prepare.prepared_files(b"not the pinned source")

    def test_print_macros_precede_all_crate_modules_and_preserve_headers(self):
        data = archive()
        with patch.object(prepare, "SHA256", hashlib.sha256(data).hexdigest()):
            files = prepare.prepared_files(data)
        source = files["src/lib.rs"].decode()
        self.assertTrue(source.startswith("//! header\n#![allow(dead_code)]\n"))
        for name in ("eprintln", "println", "eprint", "print"):
            self.assertLess(source.index("macro_rules! " + name), source.index("pub mod audio;"))
        self.assertIn('crate-type = ["rlib"]', files["Cargo.toml"].decode())

    def test_symlink_and_parent_traversal_are_rejected(self):
        for name, kind in [("src/link.rs", tarfile.SYMTYPE), ("../escape", tarfile.REGTYPE)]:
            member = tarfile.TarInfo(f"pocket-tts-ios-{prepare.REVISION}/{name}")
            member.type = kind; member.linkname = "/tmp/elsewhere"
            data = archive(member)
            with patch.object(prepare, "SHA256", hashlib.sha256(data).hexdigest()):
                with self.assertRaises(ValueError): prepare.prepared_files(data)


if __name__ == "__main__": unittest.main()
