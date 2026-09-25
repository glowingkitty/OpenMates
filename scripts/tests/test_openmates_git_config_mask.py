"""Low-level compatibility tests for the Git config read mask."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "scripts/openmates_git_config_mask.c"

CALLER_SOURCE = r"""
#define _GNU_SOURCE
#include <dlfcn.h>
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>

static int show_fd(int fd) {
    char value;
    ssize_t count;
    if (fd < 0) { perror("open"); return 2; }
    count = read(fd, &value, 1);
    close(fd);
    if (count < 0) { perror("read"); return 3; }
    puts(count == 0 ? "EOF" : (char[2]){value, '\0'});
    return 0;
}

int main(int argc, char **argv) {
    if (argc < 3) return 64;
    if (!strcmp(argv[1], "access")) {
        printf("%d\n", access(argv[2], R_OK)); return 0;
    }
    if (!strcmp(argv[1], "faccessat")) {
        int dir = open(argv[2], O_RDONLY | O_DIRECTORY);
        printf("%d\n", faccessat(dir, argv[3], R_OK, 0)); close(dir); return 0;
    }
    if (!strcmp(argv[1], "faccessat2")) {
        int (*call)(int, const char *, int, int) = dlsym(RTLD_DEFAULT, "faccessat2");
        int dir = open(argv[2], O_RDONLY | O_DIRECTORY);
        if (!call) return 77;
        printf("%d\n", call(dir, argv[3], R_OK, 0)); close(dir); return 0;
    }
    if (!strcmp(argv[1], "fopen") || !strcmp(argv[1], "fopen64")) {
        FILE *file = !strcmp(argv[1], "fopen") ? fopen(argv[2], "r") : fopen64(argv[2], "r");
        int value;
        if (!file) { perror("fopen"); return 2; }
        value = fgetc(file); fclose(file);
        puts(value == EOF ? "EOF" : (char[2]){(char)value, '\0'}); return 0;
    }
    if (!strcmp(argv[1], "open")) return show_fd(open(argv[2], O_RDONLY));
    if (!strcmp(argv[1], "open64")) return show_fd(open64(argv[2], O_RDONLY));
    if (!strcmp(argv[1], "openat") || !strcmp(argv[1], "openat64")) {
        int dir = open(argv[2], O_RDONLY | O_DIRECTORY);
        int fd = !strcmp(argv[1], "openat") ? openat(dir, argv[3], O_RDONLY) : openat64(dir, argv[3], O_RDONLY);
        close(dir); return show_fd(fd);
    }
    if (!strcmp(argv[1], "append-fopen")) {
        FILE *file = fopen(argv[2], "a"); if (!file) return 2;
        fputs("W", file); fclose(file); return 0;
    }
    if (!strcmp(argv[1], "append-open")) {
        int fd = open(argv[2], O_WRONLY | O_APPEND); if (fd < 0) return 2;
        if (write(fd, "W", 1) != 1) return 3;
        close(fd); return 0;
    }
    return 65;
}
"""


@pytest.fixture()
def compiled_mask(tmp_path: Path) -> tuple[Path, Path, Path]:
    project = tmp_path / "project"
    config = project / ".git" / "config"
    config.parent.mkdir(parents=True)
    config.write_text("SECRET", encoding="utf-8")
    library = tmp_path / "mask.so"
    caller_source = tmp_path / "caller.c"
    caller = tmp_path / "caller"
    caller_source.write_text(CALLER_SOURCE, encoding="utf-8")
    subprocess.run(
        [
            "/usr/bin/cc", "-std=c11", "-Wall", "-Wextra", "-Werror", "-shared", "-fPIC",
            f'-DOPENMATES_GIT_CONFIG_PATH="{config}"', str(SOURCE), "-o", str(library), "-ldl",
        ],
        check=True,
    )
    subprocess.run(
        ["/usr/bin/cc", "-std=c11", "-Wall", "-Wextra", "-Werror", str(caller_source), "-o", str(caller), "-ldl"],
        check=True,
    )
    return project, library, caller


def call(library: Path, caller: Path, *arguments: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(caller), *arguments],
        cwd=cwd,
        env={**os.environ, "LD_PRELOAD": str(library)},
        capture_output=True,
        text=True,
        check=False,
    )


# contract-test: supporting surface=cli assertions=code-run.remote.private-path-deny
def test_exact_config_read_apis_receive_an_empty_view(compiled_mask: tuple[Path, Path, Path]) -> None:
    project, library, caller = compiled_mask
    config = project / ".git" / "config"
    for operation in ("access", "fopen", "fopen64", "open", "open64"):
        result = call(library, caller, operation, str(config))
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == ("0" if operation == "access" else "EOF")


# contract-test: supporting surface=cli assertions=code-run.remote.private-path-deny
def test_relative_and_dirfd_paths_are_resolved_lexically(compiled_mask: tuple[Path, Path, Path]) -> None:
    project, library, caller = compiled_mask
    child = project / "src"
    child.mkdir()
    relative = "../.git/./config"
    result = call(library, caller, "fopen", relative, cwd=child)
    assert result.returncode == 0
    assert result.stdout.strip() == "EOF"
    for operation in ("faccessat", "faccessat2", "openat", "openat64"):
        result = call(library, caller, operation, str(child), relative)
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == ("0" if operation.startswith("faccess") else "EOF"), operation


# contract-test: supporting surface=cli assertions=code-run.remote.private-path-deny
def test_writes_and_unrelated_files_are_never_redirected(compiled_mask: tuple[Path, Path, Path]) -> None:
    project, library, caller = compiled_mask
    config = project / ".git" / "config"
    ordinary = project / "ordinary.txt"
    ordinary.write_text("NORMAL", encoding="utf-8")
    normal_read = call(library, caller, "open", str(ordinary))
    assert normal_read.stdout.strip() == "N"

    assert call(library, caller, "append-fopen", str(config)).returncode == 0
    assert call(library, caller, "append-open", str(config)).returncode == 0
    assert config.read_text(encoding="utf-8") == "SECRETWW"


# contract-test: supporting surface=cli assertions=code-run.remote.private-path-deny
def test_current_git_status_uses_the_empty_local_config(compiled_mask: tuple[Path, Path, Path]) -> None:
    git = shutil.which("git")
    if git is None:
        pytest.skip("git is not installed")
    project, library, _caller = compiled_mask
    subprocess.run([git, "init", "-q", str(project)], check=True)
    config = project / ".git" / "config"
    config.write_text('[remote "origin"]\n\turl = https://token@example.invalid/repo.git\n', encoding="utf-8")
    environment = {**os.environ, "LD_PRELOAD": str(library)}

    status = subprocess.run([git, "status", "--short"], cwd=project, env=environment, capture_output=True, text=True)
    assert status.returncode == 0, status.stderr
    local_url = subprocess.run(
        [git, "config", "--local", "--get", "remote.origin.url"],
        cwd=project,
        env=environment,
        capture_output=True,
        text=True,
    )
    assert local_url.returncode == 1
    assert local_url.stdout == ""


# contract-test: supporting surface=cli assertions=code-run.remote.private-path-deny
def test_production_source_keeps_fixed_scope_and_installer_marker() -> None:
    source = SOURCE.read_text(encoding="utf-8")
    assert "/* Managed by OpenMates remote-command AppArmor installer. */" in source
    assert '#define OPENMATES_GIT_CONFIG_PATH "/project/.git/config"' in source
    assert "getenv(" not in source
