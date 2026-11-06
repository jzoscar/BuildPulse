from pathlib import Path

from buildpulse import container


def test_wrap_mounts_paths_at_same_location_and_keeps_command():
    cmd = container.wrap(["cmake", "--preset", "x"], "img", Path("/p"), [Path("/p"), Path("/b"),
                         Path("/p")], platform="linux/amd64")
    assert cmd[:3] == ["docker", "run", "--rm"]
    assert cmd[cmd.index("-w") + 1] == "/p"
    assert cmd[cmd.index("--platform") + 1] == "linux/amd64"
    mounts = [cmd[i + 1] for i, a in enumerate(cmd) if a == "-v"]
    assert mounts == ["/p:/p", "/b:/b"]
    assert cmd[-4:] == ["img", "cmake", "--preset", "x"]


def test_wrap_without_platform():
    assert "--platform" not in container.wrap(["true"], "img", Path("/p"), [Path("/p")])
