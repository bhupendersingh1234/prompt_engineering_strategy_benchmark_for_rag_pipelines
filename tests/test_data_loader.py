import config
from src import data_loader


def test_build_dataset_from_fixture(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "PROCESSED_DATASET_PATH", tmp_path / "eval.jsonl")
    monkeypatch.setattr(config, "CALIBRATION_SET_PATH", tmp_path / "cal.jsonl")
    monkeypatch.setattr(config, "DATA_PROCESSED_DIR", tmp_path)

    eval_rows, cal_rows, corpus = data_loader.build_dataset(
        sample_size=5, calibration_size=4, seed=1, use_fixture=True
    )

    assert 0 < len(eval_rows) <= 5
    assert 0 < len(cal_rows) <= 4
    assert corpus, "corpus should contain at least one document"

    for row in eval_rows:
        assert row["query"]
        assert row["reference_context"]

    for row in cal_rows:
        assert "is_hallucinated" in row

    # eval and calibration sets must not overlap
    eval_ids = {r["id"] for r in eval_rows}
    cal_ids = {r["id"] for r in cal_rows}
    assert eval_ids.isdisjoint(cal_ids)

    assert (tmp_path / "eval.jsonl").exists()
    assert (tmp_path / "cal.jsonl").exists()
    assert (tmp_path / "corpus.jsonl").exists()
