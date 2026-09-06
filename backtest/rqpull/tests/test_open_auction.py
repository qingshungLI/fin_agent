from rqpull.tasks.open_auction import run


def test_open_auction_task_is_importable():
    assert callable(run)
