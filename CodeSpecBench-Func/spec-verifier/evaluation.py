from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Union, Iterable, Dict

from tqdm import tqdm

from data import LC_SPEC_DS, read_problems, stream_jsonl, write_jsonl
from execution import check_correctness

import re,os,random,ast
from collections import defaultdict

def openai_completion_process(completion):
    # First, remove content between <think> tags if they exist
    # QWQ推理结果没有<think>
    if completion.find("</think>") != -1:
        # Remove the entire <pytest> section including the tags
        end_idx = completion.find("</think>") + len("</think>")
        completion = completion[end_idx:]
    
    # # Locate markers
    # left_tag = completion.find("```python")
    # right_tag = completion.rfind("```")

    # # Choose left boundary: whichever exists and is larger
    # if left_tag == -1:
    #     # No markers at all, return raw
    #     left = 0
    # else:
    #     left = left_tag + len("```python")

    # # Choose right boundary: whichever exists and is smaller
    # if right_tag == -1:
    #     right = len(completion)
    # else:
    #     right = right_tag

    # Extract and verify code
    # completion = completion[left:right].strip()


    # 找到所有代码块包裹内容
    pattern = r"```python\s*([\s\S]*?)```"
    find_completions = re.findall(pattern, completion)

    if not find_completions:
        return None  # 或者抛出异常、返回空字符串等，根据你的需求调整

    # 找出内容最长的那个代码块
    completion = max(find_completions, key=lambda x: len(x.strip()))

    try:
        tree = ast.parse(completion)
        return completion
    
    except Exception as e:
        return None
def evaluate_functional_correctness(
    sample_file: str,
    n_workers: int = 4,
    timeout: float = 3.0,
    problem_file: str = LC_SPEC_DS,
    BATCH_SIZE: int = 10000,
):
    """
    Evaluates the functional correctness of generated samples, and writes
    results to f"{sample_file}_results.jsonl.gz"
    """
    # Finally, save the results in one file:
    def combine_results():
        for sample in stream_jsonl(sample_file):
            sample['test_cases_results']=results[sample["task_id"]]
            yield sample
    
    # 读取已验证的测试用例结果
    out_file = sample_file + "_results.jsonl.gz"
    results = defaultdict(list)
    verified_results_dict=defaultdict(list)
    if os.path.exists(out_file):
        verified_results = stream_jsonl(out_file)
        for verified_result in verified_results:
            task_id = verified_result["task_id"]
            results[task_id]=verified_result.get('test_cases_results',[])
            for test_cases_result in verified_result.get('test_cases_results',[]):
                verified_results_dict[task_id].append(test_cases_result['test_case']['test_input_params'])    

    # 读取问题
    n_samples = 0
    submit_cnt=0
    verified_cnt=0
    no_completion_cnt=0
    no_task_cnt=0
    
    print("Reading samples...")
    problems = read_problems(problem_file)
    allbatch = []
    for sample in stream_jsonl(sample_file):
        task_id = sample["task_id"]
        completion = openai_completion_process(sample["completion"])
        
        if completion is None:
            no_completion_cnt+=1
            continue
        
        if task_id not in problems:
            no_task_cnt+=1
            continue

        for test_case in problems[task_id]['test_cases']:
            
            if task_id in verified_results_dict and test_case['test_input_params'] in verified_results_dict[task_id]:
                verified_cnt+=1
                continue
            
            args = (problems[task_id], completion, timeout, test_case)
            allbatch.append(args)
            
            submit_cnt+=1
        n_samples += 1
        
    print(f"no completion:{no_completion_cnt} tasks")
    print(f"no task:{no_task_cnt} tasks")
    print(f"verified:{verified_cnt} test cases")
    print(f"submit:{submit_cnt} test cases")
    print("Running test suites...")
    
    random.shuffle(allbatch)
    # Check the generated samples against test suites.
    with ThreadPoolExecutor(max_workers=n_workers) as executor:
        batch=[]
        for args in tqdm(allbatch,position=1):
            batch.append(args)
            # 达到批次大小时提交并等待部分完成
            if len(batch) >= BATCH_SIZE:
                for future in tqdm(
                    as_completed(executor.submit(check_correctness, *args)
                    for args in tqdm(batch,position=0,leave=True,desc="submit")),
                    total=len(batch),position=0,leave=True,desc="complete"):
                    
                    result = future.result()
                    results[result["task_id"]].append(result)
                batch = []
                tqdm.write(f"Writing results to {out_file}...")
                write_jsonl(out_file, tqdm(combine_results(), total=n_samples,position=0,leave=True,desc="write"))
                
        # 处理剩余批次
        if batch:
            for future in tqdm(
                as_completed(executor.submit(check_correctness, *args)
                for args in tqdm(batch,position=0,leave=True,desc="submit")),
                total=len(batch),position=0,leave=True,desc="complete"):
                
                result = future.result()
                results[result["task_id"]].append(result)
            tqdm.write(f"Writing results to {out_file}...")
            write_jsonl(out_file, tqdm(combine_results(), total=n_samples,position=0,leave=True,desc="write"))