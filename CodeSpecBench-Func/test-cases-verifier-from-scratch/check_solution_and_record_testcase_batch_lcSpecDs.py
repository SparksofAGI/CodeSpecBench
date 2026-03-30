"""
验证和爬取测试用例
"""
import os,sys
import os.path

from utils import read_jsonl, write_jsonl,read_jsonl_gz,append_jsonl,build_testcase_string_for_submit,return_test_input_params
from leetcode_spider import Client
from loguru import logger
import time
from leetcode_spider.api import (
    invoke_interpret_solution,
    invoke_check
)
import json
from pathlib import Path
import urllib3
from tqdm import tqdm
from copy import deepcopy
import random

from collections import deque,defaultdict,Counter
import threading
import concurrent.futures
import ast

def build_unchecked_test_cases(problem_filepath,completion_save_path):
    problems = read_jsonl_gz(problem_filepath)
    if os.path.exists(completion_save_path):
        completions=read_jsonl(completion_save_path)
    else:
        completions=[]
    # 创建一个字典，用于存储已经checked每个问题对应的测试用例
    completions_test_cases_dict={}
    for completion in completions:
        test_cases=completion['test_cases'].replace(' ','')
        if completion['slug'] in completions_test_cases_dict:
            completions_test_cases_dict[completion['slug']].append(test_cases)
        else:
            completions_test_cases_dict[completion['slug']]=[test_cases]
            
    # 查看测试样例的个数和正确错误的分布
    # 第一个是正确的个数，第二个是错误的个数
    sampled_ids = []
    questions_data=defaultdict(list)
    for d in completions:
        if d['result']=='pass':
            questions_data[d['slug']].append(10)
        else:
            questions_data[d['slug']].append(d['result']['status_code'])
    questions_cnt={}
    for k,v in questions_data.items():
        questions_cnt[k]=Counter(v)
    for k,v in questions_cnt.items():
        if v[15]>=50:
            sampled_ids.append(k)
    # 遍历问题，构建没有测试的测试用例
    unchecked_test_cases=[]
    for problem in problems:
        # 跳过付费问题
        if problem['isPaidOnly']==True:
            continue
        # 测试样例足够了
        if problem['task_id'] in sampled_ids:
            continue
        for test_case in problem['test_cases']:
            # 如果已经有结果，则跳过
            if 'run_success' in test_case:
                continue
            # 提取test_input_params
            if 'test_input_params' in test_case:
                test_input_params=test_case['test_input_params']
            else:
                # 从test_input提取test_input_params
                test_input_params=return_test_input_params(test_case['test_input'])
                # 提取失败，跳过
                if  test_input_params==None:
                    continue
            # 测试能不能生成正确的testcases_string
            try:
                testcases_string=build_testcase_string_for_submit([test_input_params])
            except:
                continue
            if testcases_string == '':
                continue
            # 如果已经checked，则跳过
            if problem['task_id'] in completions_test_cases_dict and test_input_params.replace(' ','') in completions_test_cases_dict[problem['task_id']]:
                continue
            unchecked_test_cases.append(dict(
                task_id=problem['task_id'],
                test_input_params=test_input_params,
                testcases_string=testcases_string,
                question_id=problem['question_id'],
                completion=problem['completion'],
                hasCaseIdx=problem['hasCaseIdx'],
                params_num=problem['params_num'],
            ))
    return unchecked_test_cases

def merge_test_cases(unchecked_test_cases):
    unchecked_test_cases_batch_dict={}
    unchecked_test_cases_batch=[]
    batch_cnt=0
    for problem in unchecked_test_cases:
        # 先将hasCaseIdx的merge
        if problem['hasCaseIdx']==True:
            # 测试样例参数个数正确
            if problem['testcases_string'].count('\n')==problem['params_num']-1:
                batch_cnt+=1
                # 第一次出现
                if problem['task_id'] not in unchecked_test_cases_batch_dict:
                    unchecked_test_cases_batch_dict[problem['task_id']]=dict(
                        task_id=problem['task_id'],
                        test_input_params=[problem['test_input_params']],
                        question_id=problem['question_id'],
                        completion=problem['completion'],
                        hasCaseIdx=problem['hasCaseIdx'],
                    )
                # 不是第一次出现
                else:
                    unchecked_test_cases_batch_dict[problem['task_id']]['test_input_params'].append(problem['test_input_params'])
            # 测试样例参数个数不正确
            else:
                continue
                # unchecked_test_cases_batch.append(problem)
        # 再将not hasCaseIdx的append
        else:
            unchecked_test_cases_batch.append(problem)
            
    unchecked_test_cases_batch.extend(list(unchecked_test_cases_batch_dict.values()))
    logger.info(f"batch数量为{batch_cnt}")
    return unchecked_test_cases_batch

def post_process_batch_result(task,run_details):
    slug=task['task_id']
    # batch里有错误的测试样例，对batch里错误的位置处理
    if 'run_success' not in run_details:
        logger.error(f'run_success not in run_details,{run_details}\n')
        return None,None
    
    candidates=task['test_input_params']
    do_results=[]
    if run_details['run_success']==False:
        try:
            case_idx=run_details['case_idx']
        except KeyError as e:
            logger.error(f'{slug} has no case_idx,{run_details}\n')
            # 计算分割点
            split_point = len(task['test_input_params']) // 2
            if split_point==0:
                task['test_input_params']=task['test_input_params'][0]
                return None,task
            # 创建第一个新任务
            task1 = deepcopy(task)
            task1['test_input_params'] = task['test_input_params'][:split_point]
            if len(task1['test_input_params'])==1:
                task1['test_input_params']=task1['test_input_params'][0]
            # 创建第二个新任务
            task2 = deepcopy(task)
            task2['test_input_params'] = task['test_input_params'][split_point:]
            if len(task2['test_input_params'])==1:
                task2['test_input_params']=task2['test_input_params'][0]
            logger.info(f"{len(task['test_input_params'])} test_input_params分割为 {split_point}")
            return None,[task1, task2]

        # 处理这次爬虫的结果
        # 通过的测试样例
        for candidate in candidates[:case_idx]:
            do_results.append(dict(slug=slug,test_cases=candidate,result='pass',comeFrom=comeFrom))

        # 报错的测试样例
        try:
            do_results.append(dict(slug=slug,test_cases=candidates[case_idx],result=run_details,comeFrom=comeFrom))

            # 如果case_idx是最后一个，说明测完了
            if case_idx+1==len(candidates):
                undo_tasks=None
            # case_idx是batch中间的一个
            else:                           
                # 将candidates定位到错误的下一个，将报错之后的测试样例继续测试
                task['test_input_params']=candidates[case_idx+1:]
                undo_tasks=task
        except IndexError as e:
            logger.error(f"{slug} IndexError: {e}\nlen(candidates)={len(candidates)},case_idx={case_idx}")
            undo_tasks=None
    # batch里全对，说明测完了
    else:
        ## 处理这次爬虫的结果，所有测试样例都通过
        idx_flag=False
        for idx,candidate in enumerate(candidates):
            j_temp_run_details=deepcopy(run_details)
            try:
                j_temp_run_details['code_answer']=[j_temp_run_details['code_answer'][idx],'']
                j_temp_run_details['expected_code_answer']=[j_temp_run_details['expected_code_answer'][idx],'']
            except Exception as e:
                j_temp_run_details='pass'
                idx_flag=True
                no_idx_error=e
            do_results.append(dict(slug=slug,test_cases=candidate,result=j_temp_run_details,comeFrom=comeFrom))
            undo_tasks=None
        if idx_flag==True:
            logger.error(f'无法定位code_answer idx:{str(no_idx_error)}\n run_details:{run_details}')
    return do_results,undo_tasks
def check_testcase(client, task):
    slug=task['task_id']
    q_id=str(task['question_id'])
    completion_code=task['completion']
    
    if isinstance(task['test_input_params'], list):
        candidates=task['test_input_params']
    elif isinstance(task['test_input_params'], str):
        candidates=[task['test_input_params']]
    else:
        logger.error(f'slug:{slug} test_input_params is not list or str')
        raise Exception('slug:{slug} test_input_params is not list or str')
        
    try:
        testcases_string = build_testcase_string_for_submit(candidates)
    except:
        logger.warning(f'slug:{slug} build_testcase_string_for_submit error')
        return None,client,task,True
    
    try:
        details, exp_id, run_id, result, normal_flag = invoke_interpret_solution(
            client, slug, testcases_string, q_id, completion_code
        )
        
        if run_id is None:
            return None,client,task,normal_flag 
            
        run_details = invoke_check(client, run_id)
        
    except Exception as e:
        normal_flag=False
        logger.warning(e)
        return None,client,task,normal_flag

    # 对测试样例返回的结果处理
    if isinstance(task['test_input_params'], list):
        do_results,undo_tasks=post_process_batch_result(task,run_details)
        return (do_results,undo_tasks),client,task,normal_flag
    elif isinstance(task['test_input_params'], str):
        return ([dict(slug=slug,test_cases=candidates[0],result=run_details,comeFrom=comeFrom)],None),client,task,normal_flag
def check_testcases_multi_process(save_interval=100,max_workers=3):   
    unchecked_test_cases=build_unchecked_test_cases(problem_filepath,completion_save_path)
    unchecked_test_cases_batch=merge_test_cases(unchecked_test_cases)
    if len(unchecked_test_cases_batch)==0:
        sys.exit()
    random.shuffle(unchecked_test_cases_batch)
    
    pbar = tqdm(total=len(unchecked_test_cases), desc="Processing Test Cases", unit="test_case")
    
    cookies_ds = read_jsonl(cookies_filepath)
    # Shuffle the list in place
    random.shuffle(cookies_ds)
    
    clients=[]
    for cookies_d in cookies_ds:
        try:
            client = Client(cookie=cookies_d['cookie'])
        except:
            print(cookies_d['name'])
            raise
        client.login() 
        clients.append(client)

    client_queue = deque(clients)
    task_queue = deque(unchecked_test_cases_batch)

    active_futures = set()
    queue_lock = threading.Lock()

    def get_next_params():
        with queue_lock:
            if not task_queue or not client_queue:
                return None, None
            client = client_queue.popleft()
            task = task_queue.popleft()
            return client, task

    def maybe_submit_next_task():
        with queue_lock:
            return bool(task_queue and client_queue)
        
        
    def count_lines(filename):
        with open(filename, 'rb') as f:
            return sum(1 for _ in f)
        
    current_batch=[]
    last_save_time = time.time()  # Track the initial save time
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit initial tasks
        for _ in range(min(max_workers, len(unchecked_test_cases_batch), len(clients))):
            client, task = get_next_params()
            if client and task:
                future = executor.submit(check_testcase, client, task)
                active_futures.add(future)
            else:
                logger.warning('No more tasks or clients available.')

        while True:
            # 先尝试获取已完成的任务
            done, _ = concurrent.futures.wait(
                active_futures,
                timeout=100, 
                return_when=concurrent.futures.FIRST_COMPLETED
            )

            for future in done:
                active_futures.remove(future)
                result = future.result()
                
                if result is not None:
                    test_case_result, client,task,normal_flag = result

                    if normal_flag:
                        with queue_lock:
                            client_queue.append(client)  # 复用客户端
                        if test_case_result is not None:
                            do_results,undo_tasks=test_case_result
                            if do_results is not None:
                                current_batch.extend(do_results)
                                tqdm.write(f"{task['task_id']} Success {len(do_results)}")
                                pbar.update(len(do_results))  # <<< 更新进度
                            if undo_tasks is not None:
                                with queue_lock:
                                    if isinstance(undo_tasks, list):
                                        task_queue.extend(undo_tasks)
                                    elif isinstance(undo_tasks, dict):
                                        task_queue.append(undo_tasks)  # 复用任务
                        else:
                            pbar.update(len(task['test_input_params']))  # <<< 更新进度
                            
                    else:
                        logger.warning(f"One Client failed")
                        with queue_lock:
                            task_queue.append(task)  # 复用任务

            # 提交新任务
            while len(active_futures) < 5 and maybe_submit_next_task():
                client, task = get_next_params()
                if client and task:
                    future = executor.submit(check_testcase, client, task)
                    active_futures.add(future)
                else:
                    logger.warning('No more tasks or clients available.')

            # 定期保存
            current_time = time.time()
            if current_time - last_save_time >= save_interval and len(current_batch) > 0:
                append_jsonl(current_batch,completion_save_path)
                logger.info(f"Total {count_lines(completion_save_path)} test cases saved")
                current_batch.clear()
                last_save_time = current_time  # Update last save time
                
            # 退出条件：没有活跃任务、也没有待处理任务和客户端
            if not active_futures and not maybe_submit_next_task():
                break

    if current_batch:
        append_jsonl(current_batch,completion_save_path)
        logger.info(f"Total {count_lines(completion_save_path)} test cases saved")
    pbar.close()  # <<< 关闭进度条

    return not task_queue, not client_queue

if  __name__ == "__main__":
    
    urllib3.disable_warnings()
    
    # 配置 logger
    logger.remove()
    logger.add(lambda msg: tqdm.write(msg, end=""), level="INFO", colorize=True)
    logger.add("test-cases-verifier-from-scratch/check_solution_and_record_testcase_batch_lcSpecDs.log", level="DEBUG", rotation="10 MB")

    completion_save_path = 'test-cases-verifier-from-scratch/verified-result/checked_test_cases.jsonl'
    problem_filepath='test-cases-gen/lc_spec_ds.jsonl.gz'
    cookies_filepath='test-cases-verifier-from-scratch/cookies_dict.jsonl'

    comeFrom='lc_spec_ds'
    
    wait_time=7200
    while True:
        task_finish_flag,client_finish_flag=check_testcases_multi_process(save_interval=120,max_workers=3)
        if task_finish_flag is True:
            logger.info('task_finish_flag is True')
            
        if client_finish_flag is True:
            logger.info(f'client_finish_flag is True, wait {wait_time}')
            time.sleep(wait_time)
            
        