from buildpulse import cache

STATS = """\
Cacheable calls:     5 /   6 (83.33%)
  Hits:              4 /   5 (80.00%)
    Direct:          4 /   4 (100.0%)
    Preprocessed:    0 /   4 ( 0.00%)
  Misses:            1 /   5 (20.00%)
Uncacheable calls:   1 /   6 (16.67%)
"""


SCCACHE_STATS = """\
Compile requests                      6
Compile requests executed             5
Cache hits                            4
Cache hits (C/C++)                    4
Cache misses                          1
Cache misses (C/C++)                  1
"""


def test_parse_ccache_stats():
    assert cache.parse_stats("ccache", STATS) == {"hits": 4, "misses": 1, "cacheable_calls": 5}
    assert cache.parse_stats("ccache", "nothing here") is None


def test_parse_sccache_stats():
    assert cache.parse_stats("sccache", SCCACHE_STATS) == {
        "hits": 4, "misses": 1, "cacheable_calls": 5,
    }


def test_compiler_cache_choice(monkeypatch):
    monkeypatch.setattr(cache, "tool_available", lambda tool, image: tool == "sccache")
    assert cache.pick_compiler_cache("auto", None) == "sccache"
    assert cache.pick_compiler_cache("ccache", None) is None
    assert cache.pick_compiler_cache("none", None) is None


def test_describe_compiler_cache_reads_old_reports():
    assert cache.describe_compiler_cache({"ccache": True}) == "ccache"
    assert cache.describe_compiler_cache({"compiler_cache": None}) == "off"
    assert cache.describe_compiler_cache({"compiler_cache": "sccache"}) == "sccache"


def test_warm_cache_is_per_environment(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "tool_available", lambda tool, image: tool == "ccache")
    host = cache.resolve(tmp_path, None)
    image = cache.resolve(tmp_path, "buildpulse/cross-arm64")
    assert host.conan_home == tmp_path / "conan2" / "host"
    assert image.conan_home == tmp_path / "conan2" / "buildpulse-cross-arm64"
    assert image.compiler_cache_dir == tmp_path / "ccache" / "buildpulse-cross-arm64"
    assert host.env == {
        "CONAN_HOME": str(host.conan_home), "CCACHE_DIR": str(host.compiler_cache_dir),
    }


def test_cold_cache_is_throwaway(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "tool_available", lambda tool, image: True)
    cold = cache.resolve(tmp_path, None, conan_cache=False, compiler_cache="none")
    assert cold.conan_build == "*"
    assert cold.compiler_cache is None and "CCACHE_DIR" not in cold.env
    assert cold.conan_home.is_dir()
    cold.cleanup()
    assert not cold.conan_home.exists()
