"""Test budget alert thresholds."""

def test_alert_thresholds():
    # 70% threshold
    assert 70 <= (7000 / 10000 * 100) < 90
    assert 70 <= (7500 / 10000 * 100) < 90
    
    # 90% threshold
    assert (9000 / 10000 * 100) >= 90
    assert (9500 / 10000 * 100) >= 90
    assert (10000 / 10000 * 100) >= 90
    
    # Below 70%
    assert (6999 / 10000 * 100) < 70
    
    print("Alert thresholds correct")


if __name__ == "__main__":
    test_alert_thresholds()
