from buildpulse import cache

STATS = """\
Cacheable calls:     5 /   6 (83.33%)
  Hits:              4 /   5 (80.00%)
    Direct:          4 /   4 (100.0%)
    Preprocessed:    0 /   4 ( 0.00%)
  Misses:            1 /   5 (20.00%)
Uncacheable calls:   1 /   6 (16.67%)
"""


def test_parse_ccache_hits():
    assert cache.parse_ccache_hits(STATS) == {"hits": 4, "misses": 1, "cacheable_calls": 5}
    assert cache.parse_ccache_hits("nothing here") is None


def test_warm_cache_is_per_environment(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "ccache_available", lambda image: True)
    host = cache.resolve(tmp_path, None)
    image = cache.resolve(tmp_path, "buildpulse/cross-arm64")
    assert host.conan_home == tmp_path / "conan2" / "host"
    assert image.conan_home == tmp_path / "conan2" / "buildpulse-cross-arm64"
    assert image.ccache_dir == tmp_path / "ccache" / "buildpulse-cross-arm64"
    assert host.env == {"CONAN_HOME": str(host.conan_home), "CCACHE_DIR": str(host.ccache_dir)}


def test_cold_cache_is_throwaway(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "ccache_available", lambda image: True)
    cold = cache.resolve(tmp_path, None, conan_cache=False, ccache=False)
    assert cold.conan_build == "*"
    assert not cold.ccache and "CCACHE_DIR" not in cold.env
    assert cold.conan_home.is_dir()
    cold.cleanup()
    assert not cold.conan_home.exists()
