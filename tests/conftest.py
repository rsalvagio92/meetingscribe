import os
import tempfile

# Set BEFORE meetingscribe.paths is imported anywhere, so DATA_DIR resolves here.
_TMP = tempfile.mkdtemp(prefix="ms_test_")
os.environ["MEETINGSCRIBE_DATA_DIR"] = _TMP

import pytest  # noqa: E402


@pytest.fixture
def data_dir():
    return _TMP
