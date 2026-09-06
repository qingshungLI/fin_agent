from rqpull.quota import QuotaExhausted, guard


class User:
    def __init__(self, quota): self.quota = quota
    def get_quota(self): return self.quota


class RQ:
    def __init__(self, quota): self.user = User(quota)


def test_guard_allows_unlimited(tmp_path, monkeypatch):
    monkeypatch.setattr("rqpull.quota.QUOTA_LOG_PATH", tmp_path / "quota.jsonl")
    assert guard(RQ({"bytes_limit": 0, "bytes_used": 0}), min_free=999) == float("inf")


def test_guard_stops_before_limit(tmp_path, monkeypatch):
    monkeypatch.setattr("rqpull.quota.QUOTA_LOG_PATH", tmp_path / "quota.jsonl")
    try:
        guard(RQ({"bytes_limit": 1000, "bytes_used": 900}), min_free=200)
    except QuotaExhausted:
        return
    raise AssertionError("应抛出 QuotaExhausted")

