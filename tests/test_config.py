from buildpulse import config


def test_defaults_without_config_file(tmp_path):
    cfg = config.load(tmp_path)
    assert cfg.source is None
    assert cfg.project_dir == tmp_path.resolve()
    assert cfg.preset is None
    assert cfg.log_dir == (tmp_path / ".buildpulse" / "runs").resolve()


def test_config_found_from_subdirectory(tmp_path):
    (tmp_path / "buildpulse.toml").write_text(
        '[project]\ndir = "native"\npreset = "host-debug"\n\n[logs]\ndir = "out/logs"\n'
    )
    sub = tmp_path / "a" / "b"
    sub.mkdir(parents=True)

    cfg = config.load(sub)
    assert cfg.project_dir == (tmp_path / "native").resolve()
    assert cfg.preset == "host-debug"
    assert cfg.log_dir == (tmp_path / "out" / "logs").resolve()
