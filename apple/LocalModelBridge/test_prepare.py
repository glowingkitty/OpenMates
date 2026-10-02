# contract-test-file: tooling
"""Packaging checks with disposable tiny ZIP fixtures; no SDK or weight downloads."""
import hashlib
import importlib.util
import json
from pathlib import Path
import plistlib
import shlex
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import yaml

spec = importlib.util.spec_from_file_location('local_model_bridge_prepare', Path(__file__).with_name('prepare.py'))
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)


class BridgePreparationTests(unittest.TestCase):
    OVERLAY = b'// -module-name ExecuTorch\nfinal public class Tensor<T> {}\npublic func forward() {}\n'

    def fixture(self, directory, bad_arch=False):
        archive = directory / 'fixture.zip'
        prefix = 'executorch.xcframework/'
        libraries = {platform: 'libexecutorch_' + values[3] + '.a'
                     for platform, values in bridge.PLATFORMS.items()}
        slices = []
        for platform, values in bridge.PLATFORMS.items():
            supported, variant, identifier, _, _ = values
            item = {'SupportedPlatform': supported,
                    'SupportedArchitectures': ['x86_64'] if bad_arch else ['arm64'],
                    'LibraryIdentifier': identifier, 'LibraryPath': libraries[platform]}
            if variant:
                item['SupportedPlatformVariant'] = variant
            slices.append(item)
        with zipfile.ZipFile(archive, 'w') as zipped:
            zipped.writestr(prefix + 'Info.plist', plistlib.dumps({'AvailableLibraries': slices}))
            for platform, values in bridge.PLATFORMS.items():
                selected = prefix + values[2] + '/'
                zipped.writestr(selected + libraries[platform], b'disposable fixture bytes')
                zipped.writestr(selected + 'Headers/module.modulemap', b'module ExecuTorch { umbrella header "ExecuTorch/ExecuTorch.h" }')
                zipped.writestr(selected + 'ExecuTorch.swiftinterface', self.OVERLAY)
        return archive, {'name': 'executorch', 'sha256': bridge.sha256(archive),
                         'url': 'https://invalid.example/never-called', 'slice_libraries': libraries}

    def testOnlySupportedArm64PlatformsPrepareBridge(self):
        for platform in bridge.PLATFORMS:
            self.assertTrue(bridge.should_prepare(platform, 'arm64'))
            self.assertFalse(bridge.should_prepare(platform, 'x86_64'))
        self.assertTrue(bridge.should_prepare('macosx', 'arm64 x86_64'))
        self.assertFalse(bridge.should_prepare('watchos', 'arm64'))

    def testVerifiedSourcePackagesZipIsReusedWithoutNetwork(self):
        with tempfile.TemporaryDirectory(prefix='bridge-fixture-') as name:
            root = Path(name)
            cache = root / 'SourcePackages'
            cache.mkdir()
            _, artifact = self.fixture(cache)
            with patch.object(bridge.urllib.request, 'urlopen', side_effect=AssertionError('Network forbidden')):
                actual = bridge.get_archive(artifact, root / 'archives', [cache])
            self.assertEqual(bridge.sha256(actual), artifact['sha256'])
            for platform, values in bridge.PLATFORMS.items():
                output = root / 'output' / platform
                bridge.extract_slice(artifact, actual, output, platform)
                self.assertTrue((output / 'executorch.xcframework' / values[2] / 'Headers/module.modulemap').exists())
                for other in bridge.PLATFORMS.values():
                    if other[2] != values[2]:
                        self.assertFalse((output / 'executorch.xcframework' / other[2]).exists())

    def testCorruptArchiveFailsBeforeExtraction(self):
        with tempfile.TemporaryDirectory(prefix='bridge-fixture-') as name:
            root = Path(name)
            archive, artifact = self.fixture(root)
            archive.write_bytes(archive.read_bytes() + b'corruption')
            with self.assertRaisesRegex(ValueError, 'checksum'):
                bridge.extract_slice(artifact, archive, root / 'output', 'iphoneos')
            self.assertFalse((root / 'output').exists())

    def testMissingArm64SliceFailsInsteadOfFabricatingOne(self):
        with tempfile.TemporaryDirectory(prefix='bridge-fixture-') as name:
            root = Path(name)
            archive, artifact = self.fixture(root, bad_arch=True)
            for platform in bridge.PLATFORMS:
                with self.assertRaisesRegex(ValueError, 'platform slice'):
                    bridge.extract_slice(artifact, archive, root / 'output' / platform, platform)

    def testOriginalSwiftOverlaysAndModuleMapsRemainSeparatedByPlatform(self):
        with tempfile.TemporaryDirectory(prefix='bridge-fixture-') as name:
            root = Path(name)
            archive, artifact = self.fixture(root)
            output = root / 'output'
            data = {'upstream_revision': 'fixture', 'artifacts': [artifact]}
            with patch.object(bridge, 'get_archive', return_value=archive):
                for platform, values in bridge.PLATFORMS.items():
                    bridge.prepare(data, output, [], platform)
                    selected = output / platform
                    self.assertEqual((selected / 'Modules/ExecuTorch.swiftmodule' / values[4]).read_bytes(), self.OVERLAY)
                    self.assertEqual(json.loads((selected / 'receipt.json').read_text())['swift_interface_sha256'], hashlib.sha256(self.OVERLAY).hexdigest())
            self.assertFalse((output / 'include/module.modulemap').exists(), 'No shared SwiftPM include output')
            self.assertEqual(len(list(output.glob('*/executorch.xcframework/*/Headers/module.modulemap'))), 3)

    def testEveryGeneratedLinkerArchiveHasABuildGraphProducer(self):
        project = yaml.safe_load(Path(__file__).parents[1].joinpath('project.yml').read_text())
        target = project['targets']['OpenMates']
        settings = target['settings']['base']
        script = next(item for item in target['preBuildScripts'] if item['name'] == 'Prepare LocalModelBridge')
        for platform in bridge.PLATFORMS:
            variables = {
                'DERIVED_FILE_DIR': '/clean-build/DerivedSources',
                'PLATFORM_NAME': platform,
                'LOCAL_MODEL_BRIDGE_SLICE': settings[f'LOCAL_MODEL_BRIDGE_SLICE[sdk={platform}*]'],
                'LOCAL_MODEL_BRIDGE_SUFFIX': settings[f'LOCAL_MODEL_BRIDGE_SUFFIX[sdk={platform}*]'],
            }

            def resolve(value):
                for key, replacement in variables.items():
                    value = value.replace('$(' + key + ')', replacement)
                return value

            outputs = {resolve(path) for path in script['outputFiles']}
            flags = settings[f'OTHER_LDFLAGS[sdk={platform}*][arch=arm64]']
            inputs = {resolve(token) for token in shlex.split(flags) if token.endswith('.a')}
            self.assertEqual(inputs, outputs, f'{platform}: clean builds need all six generated linker inputs declared')
            self.assertEqual(len(outputs), 6)
        self.assertFalse(any('OTHER_LDFLAGS' in key and 'x86_64' in key for key in settings))

    def testCanonicalCatalogPinsSixLibrariesAndLicense(self):
        data = bridge.catalog(Path(__file__).with_name('catalog.json'))
        self.assertEqual({a['name'] for a in data['artifacts']}, bridge.NAMES)
        self.assertEqual(data['upstream_revision'], '56cc93a96d5fb8d21554ec5f00fbad5a5b228bc4')
        for artifact in data['artifacts']:
            self.assertEqual(set(artifact['slice_libraries']), set(bridge.PLATFORMS))


if __name__ == '__main__':
    unittest.main()
