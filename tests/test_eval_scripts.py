from evals.scripts.run_eval import DATASET_PATH, print_report


def test_moved_eval_dataset_path_exists():
    assert DATASET_PATH.is_file()
    assert DATASET_PATH.as_posix().endswith("evals/datasets/dataset.yaml")


def test_print_report_handles_query_only_subset(capsys):
    cases = [{"id": "E001", "category": "single_agg", "query": "一共有多少笔订单"}]
    results = [{
        "id": "E001",
        "category": "single_agg",
        "query": "一共有多少笔订单",
        "verdict": "correct",
        "correct_count": 0,
        "elapsed": 1.0,
        "generated_sql": "SELECT COUNT(*) FROM fact_order",
        "error_detail": None,
    }]

    print_report(results, cases)

    output = capsys.readouterr().out
    assert "Execution Accuracy: 1/1 = 100.0%" in output
    assert "本次未包含非查询用例" in output
