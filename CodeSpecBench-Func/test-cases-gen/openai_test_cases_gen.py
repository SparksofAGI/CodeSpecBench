from time import time,sleep
import os,json,re,ast
import argparse
from utils import read_jsonl_gz,write_jsonl,read_jsonl,openai_model_call,write_jsonl_gz,build_testcase_string_for_submit,return_test_input_params,openai_completion_process,verify_test_input
from concurrent.futures import ThreadPoolExecutor, as_completed
import fire
from tqdm import tqdm
from loguru import logger
from func_timeout.exceptions import FunctionTimedOut  # 需要额外导入



def openai_completion(ds, completions_save_path,save_interval=10,model_name='gpt-4o-mini'):
    # 定义并发调用的函数
    def process_d(d,model_name):
        start_time = time()
        
        try:
            user_prompt=PROMPT_TEMPLATE.format(PROBLEM_DESCRIPTION=d['problem_description'])
            completion=dict(task_id=d['task_id'])
            response=openai_model_call(user_prompt,model_name)
            completion['completion']=response.choices[0].message.content
            
            if completion['completion'] is None:
                raise  Exception("completion is None")
            
            cost_time = time() - start_time
            tqdm.write(f"ds_idx:{d['task_id']} - time:{cost_time:.2f}")
            
            return completion
        
        except Exception as e:
            tqdm.write(f"error -- ds_idx:{d['task_id']} -- error:{e}")
            return None
        except FunctionTimedOut as e:
            tqdm.write(f"error -- ds_idx:{d['task_id']} -- error: Time Out")
            return None
        
    # 控制速率为 100 RPM, 超过会超速率
    rate_limit = 1000 / 60  # 转换为每秒的请求数
    delay = 1 / rate_limit
    
    # # 将任务分成多个批次
    # total_tasks = len(ds)
    # num_batches = (total_tasks + batch_size - 1) // batch_size
    # for batch_start in tqdm(range(0, total_tasks, batch_size),total=num_batches,desc="Processing Batches",leave=True,position=1):
    #     batch_end = min(batch_start + batch_size, total_tasks)
    #     batch_ds = ds[batch_start:batch_end]
        
        # print(f"Processing batch {batch_start//batch_size + 1}/{(total_tasks + batch_size - 1)//batch_size}")
        
    # 使用 ThreadPoolExecutor 进行并发调用
    with ThreadPoolExecutor(max_workers=os.cpu_count()*5) as executor:
        futures = []
        for d in tqdm(ds, total=len(ds),desc="Submitting tasks"):
            future = executor.submit(process_d, d, model_name)
            futures.append(future)
            sleep(delay)  # 控制速率
        
        # 获取结果
        current_batch = []
        last_save_time = time()  # Record the time when the program starts

        for future in tqdm(as_completed(futures), total=len(futures), desc="Completing tasks"):
            completion = future.result()
            if completion is not None:
                current_batch.append(completion)

            # Check if it's time to save based on the interval
            if time() - last_save_time >= save_interval:  # If 10 seconds have passed
                if current_batch:  # Only save if there are items in the batch
                    post_process_and_save(current_batch, completions_save_path)
                    logger.info(f"Batch (remaining {len(current_batch)}) saved to {completions_save_path}")
                    current_batch.clear()  # Clear the batch after saving
                    last_save_time = time()  # Update the last save time

        # After loop, save any remaining items
        if current_batch:
            post_process_and_save(current_batch, completions_save_path)
            logger.info(f"Final batch (remaining {len(current_batch)}) saved to {completions_save_path}")
    
    logger.info(f"All tasks completed.")
def post_process_and_save(completions, completions_save_path):
    # 读取原始数据集
    ds=read_jsonl_gz(completions_save_path)
    ds_dict={d['task_id']: d for d in ds}
    # 遍历 completions
    all_cnt=0
    for completion in completions:
        # 将completion处理为list
        processed_completion=openai_completion_process(completion['completion'])
        if processed_completion is None:
            continue
        processed_list_completion=processed_completion.split("\n")

        # 获取原始数据集中的测试用例
        test_cases=ds_dict[completion['task_id']]['test_cases']
        all_test_input=[test_case['test_input'].replace(' ','') for test_case in test_cases]
        
        # 去重的测试用例并过滤掉长度不符合要求的
        dedup_processed_list_completion = [
            processed_list_completion[i] 
            for i in range(len(processed_list_completion)) 
            if processed_list_completion[i].replace(' ','') not in all_test_input 
            and 0 < len(processed_list_completion[i]) <= 1000
        ]

        valid_gen_cnt=0
        for list_completion_i in dedup_processed_list_completion:
            if verify_test_input(list_completion_i,ds_dict[completion['task_id']]['params_num']):
                test_cases.append({
                    "test_input": list_completion_i,
                })
                valid_gen_cnt+=1
                
        all_cnt+=valid_gen_cnt
        tqdm.write(f"result - ds_idx:{completion['task_id']} - test_cases:{valid_gen_cnt}")
    logger.info(f"result - all - test_cases:{all_cnt}")
    write_jsonl_gz(list(ds_dict.values()), completions_save_path)

def main(model_name='qwen-max'):
    # 配置 logger
    logger.remove()
    logger.add(lambda msg: tqdm.write(msg, end=""), level="INFO", colorize=True)
    logger.add("test-cases-gen/openai_test_cases_gen.log", level="DEBUG", rotation="10 MB")
    
    gen_times=50
    for _ in range(gen_times):
    # while True:
        path='test-cases-gen/lc_spec_ds.jsonl.gz'
        ds=read_jsonl_gz('data/CodeSpecBench-Func.jsonl.gz')
        #############################
        # 跳过已经采够样的
        sampled_ids = []
        ds_verified=read_jsonl('test-cases-verifier-from-scratch/verified-result/checked_test_cases.jsonl')
        # 查看测试样例的个数和正确错误的分布
        from collections import defaultdict,Counter
        # 第一个是正确的个数，第二个是错误的个数
        questions_data=defaultdict(list)
        for d in ds_verified:
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
        #############################
        # ds_verified=read_jsonl_gz('data/lc_spec_ds.jsonl.gz')
        # # 跳过已经采够样的
        # sampled_ids = []
        # for d in ds_verified:
        #     correct_cnt=0
        #     for test_case in d['test_cases']:
        #         if test_case['run_success']==False:
        #             correct_cnt+=1
        #     if correct_cnt>=50:
        #         sampled_ids.append(d['task_id'])
        #############################
        # 过滤掉付费
        ds_not_pay = [d for d in ds if d['isPaidOnly']==False]
        # 过滤掉已经采样的数据
        ds_not_enough = [d for d in ds_not_pay if d['task_id'] not in sampled_ids]
        
        if len(ds_not_enough)==0:
            break
        
        openai_completion(ds_not_enough, path,save_interval=60,model_name=model_name)
        
with open('./incorrect_pre_test_cases_gen_prompt.txt','r') as f:
    PROMPT_TEMPLATE = f.read()
    
if  __name__ == "__main__":
    fire.Fire(main)
