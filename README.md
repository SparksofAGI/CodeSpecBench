# CodeSpecBench

CodeSpecBench is a benchmark for **executable behavioral specification generation**.  
Instead of generating solutions, models generate **executable Python specifications**:

- **Preconditions**: validate inputs and relevant program state before execution  
- **Postconditions**: validate outputs and allowed state changes after execution

CodeSpecBench supports two evaluation settings:

- **CodeSpecBench-Func**: self-contained function-level tasks
- **CodeSpecBench-Repo**: realistic repository-level issues

The benchmark evaluates specifications with **execution-based** metrics:
- **Correctness**: accepts all valid behaviors/tests
- **Completeness**: rejects all invalid behaviors/tests
- **Pass Rate**: satisfies both correctness and completeness

## Repository Structure (High-Level)

```

CodeSpecBench/
CodeSpecBench-Func/
CodeSpecBench-Repo/

````


## CodeSpecBench-Func

### Build CodeSpecBench-Func

#### 1) Generate test inputs with LLMs
```bash
cd CodeSpecBench/CodeSpecBench-Func
python test-cases-gen/openai_test_cases_gen.py
````

#### 2) Validate test inputs via Online Judge (OJ)

This step submits generated inputs to the official OJ to:

* label **correct inputs** (accepted by OJ) and record ground-truth outputs
* label **incorrect inputs** (rejected by OJ) and record error info (e.g., `TypeError`)

```bash
python test-cases-verifier-from-scratch/check_solution_and_record_testcase_batch_lcSpecDs.py
```

#### 3) Merge validated data into the benchmark format

```text
Run: data/gen_lc_spec_ds.ipynb
```

#### 4) Generate incorrect postcondition test cases

This constructs incorrect outputs paired with correct inputs (e.g., type-based and numeric-based corruptions).

```text
Run: test-cases-gen/incorrect_post_test_cases_gen.ipynb
```

---

### CodeSpecBench-Func Evaluation

#### 1) Generate formal specifications

**Closed-source models**

```bash
bash spec-gen/openai_spec_gen.sh
```

**Local / open-weight models (via vLLM)**

```bash
bash spec-gen/vllm_spec_gen.sh
```

#### 2) Verify specification correctness & completeness

Runs execution-based checking over curated correct/incorrect test suites.

```bash
bash spec-verifier/evaluate_functional_correctness.sh
```

#### 3) Compute correctness, completeness, and pass rate

```text
Run: spec-stats/pass_rate.ipynb
```

---

## CodeSpecBench-Repo

Specifications are dynamically injected around issue-relevant target function(s):

* precondition runs **before** the target function to validate runtime inputs/state
* postcondition runs **after** to validate outputs and state updates

### Install

```bash
cd CodeSpecBench/CodeSpecBench-Repo
pip install -e .
```

### Generate formal specifications

```bash
bash chatgpt_api_inference.sh
```

### Verify correctness & completeness

```bash
bash run.sh
```

### Compute correctness, completeness, and pass rate

```text
Run: llm_accuracy_calculation.ipynb
```