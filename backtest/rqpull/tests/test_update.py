import pandas as pd

from rqpull.tasks.update import _ready


def test_ready_shapes():
    assert _ready(True)
    assert _ready({"ready": True})
    assert _ready(pd.DataFrame({"ready": [True, True]}))
    assert not _ready(pd.DataFrame({"ready": [True, False]}))
