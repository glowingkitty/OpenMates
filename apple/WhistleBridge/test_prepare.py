# contract-test-file: tooling
"""Focused packaging boundary tests. No native compilation or binary execution."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('whistle_prepare', HERE / 'prepare.py')
prepare = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prepare)


class PackagingTests(unittest.TestCase):
    def testAllPinsAreOfficialImmutableAndOnlyWhistleWeights(self):
        lock = prepare.pinned_files()
        weights = [x for x in lock['files'] if x['path'].endswith('.cact')]
        self.assertEqual([x['path'] for x in weights], ['whistle.cact'])
        self.assertEqual(weights[0]['sizeBytes'], 16_919_407)
        self.assertEqual(weights[0]['sha256'], 'b6e02f048568ac5d01a2042556c658061e699acbc0aa2a1439f52f3d461dffeb')
        self.assertFalse(lock['runtime']['capabilities']['deterministicUnload'])
        self.assertEqual(lock['runtime']['platforms']['watchos-arm64']['architectures'], ['arm64_32', 'arm64'])

    def testWatchSimulatorCannotAccidentallyUseDeviceLibrary(self):
        with tempfile.TemporaryDirectory(dir=HERE) as directory:
            root = Path(directory)
            with self.assertRaisesRegex(ValueError, 'unsupported_runtime_platform:watchsimulator'):
                prepare.prepare(root / 'cache', root / 'output', 'watchsimulator')
            self.assertFalse((root / 'output').exists())

    def testDefaultPreparationIsOffline(self):
        with tempfile.TemporaryDirectory(dir=HERE) as directory, patch.object(prepare.urllib.request, 'urlopen') as network:
            with self.assertRaisesRegex(ValueError, 'offline_asset_missing'):
                prepare.prepare(Path(directory) / 'cache', Path(directory) / 'output', 'iphoneos')
            network.assert_not_called()

    def testDigestMismatchIsRejectedBeforeProductCreation(self):
        with tempfile.TemporaryDirectory(dir=HERE) as directory:
            root = Path(directory)
            entry = {'path': 'test.cact', 'sizeBytes': 4, 'sha256': hashlib.sha256(b'good').hexdigest()}
            asset = root / 'test.cact'
            asset.write_bytes(b'evil')
            with self.assertRaisesRegex(ValueError, 'asset_verification_failed'):
                prepare.verify(asset, entry)

    def testSymlinkIsRejected(self):
        with tempfile.TemporaryDirectory(dir=HERE) as directory:
            root = Path(directory)
            target = root / 'real'
            target.write_bytes(b'good')
            link = root / 'link'
            link.symlink_to(target)
            with self.assertRaisesRegex(ValueError, 'asset_verification_failed'):
                prepare.verify(link, {'path': 'link', 'sizeBytes': 4, 'sha256': hashlib.sha256(b'good').hexdigest()})

    def testModelOnlySimulatorPackageContainsNoDeviceLinkInput(self):
        prepare.pinned_files()
        with tempfile.TemporaryDirectory(dir=HERE) as directory:
            root = Path(directory)
            def fixture(cache, entry, fetch):
                target = root / entry['repository'].split('/')[1] / entry['path']
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b'fixture')
                return target
            with patch.object(prepare, 'obtain', side_effect=fixture), patch.object(prepare, 'verify'):
                receipt = prepare.prepare(root / 'cache', root / 'out', 'watchsimulator', model_only=True)
            self.assertFalse((root / 'out/link').exists())
            self.assertFalse(receipt['nativeActivationAllowed'])
            self.assertEqual(receipt['documentsBytes'], 0)
            self.assertEqual(receipt['modelResidency'], 'process_lifetime')
            self.assertFalse(receipt['reclaimsModelOnSessionEnd'])

    def testUnsafeManifestPathIsRejected(self):
        lock = prepare.pinned_files()
        lock['files'][0]['path'] = '../escape.cact'
        with tempfile.TemporaryDirectory(dir=HERE) as directory:
            root = Path(directory)
            (root / 'whistle-assets.lock.json').write_text(json.dumps(lock))
            with patch.object(prepare, 'ROOT', root):
                with self.assertRaisesRegex(ValueError, 'unsafe_asset_path'):
                    prepare.pinned_files()


if __name__ == '__main__':
    unittest.main()
