from document_ia_auto_scaler.scaler import QueueAutoScaler


def test_scaler_no_action_when_load_is_stable():
    scaler = QueueAutoScaler(
        min_workers=1,
        max_workers=5,
        thread_per_worker=10,
        scale_up_cooldown=120,
        scale_down_cooldown=300,
    )

    # Capacity is 1 * 10 = 10. Lag is 5. No scale needed.
    decision = scaler.evaluate(
        current_time=1000.0,
        last_scale_time=800.0,
        current_workers=1,
        queue_lag=5,
    )
    assert decision is None


def test_scaler_scale_up_when_overloaded_and_cooldown_expired():
    scaler = QueueAutoScaler(
        min_workers=1,
        max_workers=5,
        thread_per_worker=10,
        scale_up_cooldown=120,
        scale_down_cooldown=300,
    )

    # Capacity is 1 * 10 = 10. Lag is 15. Last scale was 200s ago (cooldown is 120s).
    decision = scaler.evaluate(
        current_time=1000.0,
        last_scale_time=800.0,
        current_workers=1,
        queue_lag=15,
    )
    assert decision == ("scale_up", 2)


def test_scaler_no_scale_up_during_cooldown():
    scaler = QueueAutoScaler(
        min_workers=1,
        max_workers=5,
        thread_per_worker=10,
        scale_up_cooldown=120,
        scale_down_cooldown=300,
    )

    # Capacity is 1 * 10 = 10. Lag is 15. Last scale was 50s ago (cooldown is 120s).
    decision = scaler.evaluate(
        current_time=1000.0,
        last_scale_time=950.0,
        current_workers=1,
        queue_lag=15,
    )
    assert decision is None


def test_scaler_no_scale_up_beyond_max_workers():
    scaler = QueueAutoScaler(
        min_workers=1,
        max_workers=3,
        thread_per_worker=10,
        scale_up_cooldown=120,
        scale_down_cooldown=300,
    )

    # Capacity is 3 * 10 = 30. Lag is 40. Cooldown expired. Max workers is 3.
    decision = scaler.evaluate(
        current_time=1000.0,
        last_scale_time=800.0,
        current_workers=3,
        queue_lag=40,
    )
    assert decision is None


def test_scaler_scale_down_when_idle_and_cooldown_expired():
    scaler = QueueAutoScaler(
        min_workers=1,
        max_workers=5,
        thread_per_worker=10,
        scale_up_cooldown=120,
        scale_down_cooldown=300,
    )

    # We have 2 workers. Lag is 0. Last scale was 400s ago (cooldown is 300s).
    decision = scaler.evaluate(
        current_time=1000.0,
        last_scale_time=600.0,
        current_workers=2,
        queue_lag=0,
    )
    assert decision == ("scale_down", 1)


def test_scaler_no_scale_down_during_cooldown():
    scaler = QueueAutoScaler(
        min_workers=1,
        max_workers=5,
        thread_per_worker=10,
        scale_up_cooldown=120,
        scale_down_cooldown=300,
    )

    # We have 2 workers. Lag is 0. Last scale was 100s ago (cooldown is 300s).
    decision = scaler.evaluate(
        current_time=1000.0,
        last_scale_time=900.0,
        current_workers=2,
        queue_lag=0,
    )
    assert decision is None


def test_scaler_no_scale_down_below_min_workers():
    scaler = QueueAutoScaler(
        min_workers=1,
        max_workers=5,
        thread_per_worker=10,
        scale_up_cooldown=120,
        scale_down_cooldown=300,
    )

    # We have 1 worker (min_workers is 1). Lag is 0. Cooldown expired.
    decision = scaler.evaluate(
        current_time=1000.0,
        last_scale_time=600.0,
        current_workers=1,
        queue_lag=0,
    )
    assert decision is None
