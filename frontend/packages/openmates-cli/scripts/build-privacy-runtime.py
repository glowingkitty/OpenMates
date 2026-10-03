"""Build pinned native assets for packaging, never on an end-user's machine."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request

PF = "735a6c28607ee82afc3a670383f41b55266a3b9a"
GGML = "3af5f5760e19a96427f5f7a93b79cbdf3d4b265b"


def download_tree(repository, revision, destination):
    archive = destination.parent / (repository.rsplit("/", 1)[-1] + ".tgz")
    urllib.request.urlretrieve(f"https://codeload.github.com/{repository}/tar.gz/{revision}", archive)
    with tarfile.open(archive) as tar:
        tar.extractall(destination.parent / "extract", filter="data")
    extracted = next((destination.parent / "extract").iterdir())
    shutil.move(extracted, destination)
    shutil.rmtree(destination.parent / "extract")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, help="Already-pinned development source")
    parser.add_argument("--cross", action="store_true", help="Ubuntu amd64 -> Linux ARM64")
    args = parser.parse_args()
    package = Path(__file__).resolve().parent.parent
    output = package / "fixtures/privacy-runtime/linux-arm64"
    shutil.rmtree(output, ignore_errors=True)
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="openmates-privacy-build-") as directory:
        temporary = Path(directory)
        source = temporary / "source"
        if args.source:
            revision = subprocess.check_output(["git", "-C", str(args.source), "rev-parse", "HEAD"], text=True).strip()
            if revision != PF:
                raise RuntimeError("Native source revision does not match")
            shutil.copytree(args.source, source, ignore=shutil.ignore_patterns(".git", "build", "__pycache__"))
        else:
            download_tree("localai-org/privacy-filter.cpp", PF, source)
            shutil.rmtree(source / "ggml", ignore_errors=True)
            download_tree("ggml-org/ggml", GGML, source / "ggml")
        wrapper = temporary / "CMakeLists.txt"
        worker = package / "native/privacy-worker.cpp"
        wrapper.write_text(f'''cmake_minimum_required(VERSION 3.21)
project(openmates_privacy C CXX)
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_BUILD_RPATH_USE_ORIGIN ON)
add_subdirectory("{source}" upstream)
add_executable(openmates-pii-worker "{worker}")
target_link_libraries(openmates-pii-worker PRIVATE pf)
set_target_properties(openmates-pii-worker PROPERTIES BUILD_RPATH "$ORIGIN")
''')
        build = temporary / "build"
        flags = ["-DCMAKE_BUILD_TYPE=Release", "-DPF_BUILD_TOOLS=OFF", "-DPF_BUILD_TESTS=OFF",
                 "-DGGML_NATIVE=OFF", "-DGGML_CPU_ARM_ARCH=armv8.2-a+fp16+dotprod",
                 "-DGGML_OPENMP=OFF", "-DBUILD_SHARED_LIBS=ON", "-DCMAKE_POSITION_INDEPENDENT_CODE=ON",
                 "-DCMAKE_CXX_FLAGS=-static-libstdc++ -static-libgcc"]
        if args.cross:
            flags += ["-DCMAKE_SYSTEM_NAME=Linux", "-DCMAKE_SYSTEM_PROCESSOR=aarch64",
                      "-DCMAKE_C_COMPILER=aarch64-linux-gnu-gcc", "-DCMAKE_CXX_COMPILER=aarch64-linux-gnu-g++"]
        subprocess.run(["cmake", "-S", str(temporary), "-B", str(build), *flags], check=True)
        subprocess.run(["cmake", "--build", str(build), "--target", "openmates-pii-worker", "-j", "4"], check=True)
        executable = output / "openmates-pii-worker"
        shutil.copy2(build / "openmates-pii-worker", executable)
        for library in build.rglob("libggml*.so*"):
            shutil.copy2(library, output / library.name)
        shutil.copy2(source / "LICENSE", output / "LICENSE.privacy-filter")
        shutil.copy2(source / "ggml/LICENSE", output / "LICENSE.ggml")
        # Static C++ runtime avoids dependence on the end user's libstdc++ version.
        # glibc remains supplied by the supported Linux host.
        manifest = {"revision": PF, "ggml_revision": GGML, "protocol": 1, "platform": "linux-arm64", "files": []}
        for file in sorted(output.iterdir()):
            if file.name == "manifest.json":
                continue
            manifest["files"].append({"name": file.name, "bytes": file.stat().st_size,
                                      "sha256": hashlib.sha256(file.read_bytes()).hexdigest()})
        (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        print("Packaged", output)


if __name__ == "__main__":
    main()
