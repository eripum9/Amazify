from pathlib import Path
import re
import tomllib

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name


ROOT = Path(__file__).resolve().parents[1]
PIN = re.compile(r"^([A-Za-z0-9_.-]+)==([^\s\\]+)", re.MULTILINE)


def pins(path: Path) -> dict[str, str]:
    return {
        canonicalize_name(name): version
        for name, version in PIN.findall(path.read_text(encoding="utf-8"))
    }


def input_pins(path: Path) -> dict[str, str]:
    result = pins(path)
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("-r "):
            result.update(input_pins(path.parent / line[3:].strip()))
    return result


def test_direct_dependency_pins_match_all_generated_locks():
    for source, lock in (
        ("requirements-runtime.in", "requirements.txt"),
        ("requirements-dev.in", "requirements-dev.lock"),
        ("requirements-build.in", "requirements-build.lock"),
    ):
        locked = pins(ROOT / lock)
        for name, version in input_pins(ROOT / source).items():
            assert locked.get(name) == version, f"Regenerate {lock}: {name} != {version}"


def test_shared_dependencies_have_consistent_versions():
    runtime = pins(ROOT / "requirements.txt")
    development = pins(ROOT / "requirements-dev.lock")
    build = pins(ROOT / "requirements-build.lock")
    for smaller, larger in ((runtime, development), (development, build)):
        for name, version in smaller.items():
            assert larger.get(name) == version, f"Inconsistent lock version for {name}"


def test_package_metadata_accepts_locked_runtime_and_build_versions():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    locked = pins(ROOT / "requirements-build.lock")
    requirements = project["dependencies"] + project["optional-dependencies"]["build"]
    for value in requirements:
        requirement = Requirement(value)
        assert locked[canonicalize_name(requirement.name)] in requirement.specifier
