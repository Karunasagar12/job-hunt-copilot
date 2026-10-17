import os

import conftest
import db


def test_db_path_is_never_the_real_pipeline_db():
    real_pipeline_db = os.path.join(os.path.dirname(os.path.abspath(db.__file__)), "pipeline.db")
    assert db.DB_PATH != real_pipeline_db
    assert os.path.dirname(db.DB_PATH) == conftest.DATA_DIR
    assert os.path.commonpath([db.DB_PATH, conftest.TEST_ROOT]) == conftest.TEST_ROOT
    assert db.DB_PATH != os.path.join(os.path.dirname(os.path.abspath(db.__file__)), "data", "pipeline.db")


def test_db_path_is_the_one_conftest_set():
    # Proves conftest.py's DB_PATH is actually load-bearing — this would still
    # pass if every test file set its own DB_PATH guard (masking conftest),
    # so it must match conftest's value specifically, not just "some temp file".
    assert db.DB_PATH == conftest.DB_PATH
