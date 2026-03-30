import fire
from data import LC_SPEC_DS
from evaluation import evaluate_functional_correctness
import os

def entry_point(
    sample_file: str,
    n_workers: int = os.cpu_count(),
    timeout: float = 3.0,
    problem_file: str = LC_SPEC_DS,
    BATCH_SIZE: int = 50000,
):
    """
    Evaluates the functional correctness of generated samples, and writes
    results to f"{sample_file}_results.jsonl.gz"
    """
    evaluate_functional_correctness(sample_file, n_workers, timeout, problem_file, BATCH_SIZE)

if  __name__ == "__main__":
    fire.Fire(entry_point)