set -e

# set TEST_COMPLETE true for completeness test
export TEST_COMPLETE=true 
export SPEC_SAVE_PATH="logs/sample_results/claude-sonnet-4-5-20250929"
python -m swebench.harness.run_evaluation_spec \
    --predictions_path gold \
    --max_workers 8 \
    --run_id claude-sonnet-4-5-20250929 \
    --dataset_name CodeSpecBench-Repo.jsonl
