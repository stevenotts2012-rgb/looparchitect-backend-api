from app.style_engine.seed import create_rng, normalize_seed


def test_normalize_seed_from_int_is_stable() -> None:
    assert normalize_seed(12345) == normalize_seed(12345)


def test_normalize_seed_from_string_is_stable() -> None:
    assert normalize_seed("atl-demo") == normalize_seed("atl-demo")


def test_create_rng_reproducible_sequence() -> None:
    seed_a, rng_a = create_rng("demo-seed")
    seed_b, rng_b = create_rng("demo-seed")
    assert seed_a == seed_b

    seq_a = [rng_a.randint(0, 1000) for _ in range(8)]
    seq_b = [rng_b.randint(0, 1000) for _ in range(8)]
    assert seq_a == seq_b
