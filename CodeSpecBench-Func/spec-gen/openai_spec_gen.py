from time import time,sleep
import os,json
import argparse
from utils import read_jsonl_gz,write_jsonl,read_jsonl,openai_model_call,append_jsonl
from concurrent.futures import ThreadPoolExecutor, as_completed
import fire
from tqdm import tqdm
from loguru import logger

with open('./PROMPT_TEMPLATE.txt','r') as f:
    PROMPT_TEMPLATE=f.read()
    
def openai_completion(ds, completions_save_path,save_interval=50,model_name='gpt-4o-mini'):
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
    
    # 控制速率为 100 RPM, 超过会超速率
    rate_limit = 100 / 60  # 转换为每秒的请求数
    delay = 1 / rate_limit
    
    # # 将任务分成多个批次
    # total_tasks = len(ds)
    # num_batches = (total_tasks + batch_size - 1) // batch_size
    # for batch_start in tqdm(range(0, total_tasks, batch_size),total=num_batches,desc="Processing Batches",leave=True):
    #     batch_end = min(batch_start + batch_size, total_tasks)
    #     batch_ds = ds[batch_start:batch_end]
        
        # print(f"Processing batch {batch_start//batch_size + 1}/{(total_tasks + batch_size - 1)//batch_size}")

    # 使用 ThreadPoolExecutor 进行并发调用
    with ThreadPoolExecutor(max_workers=os.cpu_count()*5) as executor:
        futures = []
        for d in tqdm(ds, total=len(ds),desc=f"{model_name} Submitting tasks"):
            future = executor.submit(process_d, d, model_name)
            futures.append(future)
            sleep(delay)  # 控制速率
        
        # 获取结果
        current_batch = []
        last_save_time = time()  # Record the time when the program starts

        for future in tqdm(as_completed(futures), total=len(futures), desc=f"{model_name} Completing tasks"):
            completion = future.result()
            if completion is not None:
                current_batch.append(completion)

            # Check if it's time to save based on the interval
            if time() - last_save_time >= save_interval:  # If 10 seconds have passed
                if current_batch:  # Only save if there are items in the batch
                    append_jsonl(current_batch, completions_save_path)
                    current_batch.clear()  # Clear the batch after saving
                    last_save_time = time()  # Update the last save time

        # After loop, save any remaining items
        if current_batch:
            append_jsonl(current_batch, completions_save_path)
    
    logger.info(f"All tasks completed.")



def main(model_name):
    logger.add('./openai_spec_gen.log')
    while True:
        ds=read_jsonl_gz('../data/CodeSpecBench-Func.jsonl.gz')
        completions_save_path=f'./sample_results/{model_name}.jsonl'

        completions = []
        sampled_ids = []
        
        # 跳过已经采样的
        if os.path.exists(completions_save_path):
            completions_proto = read_jsonl(completions_save_path)
            
            # 筛选掉采样错误的
            for completion in completions_proto:
                if 'completion' in completion:
                    completions.append(completion)
            
            # 拿出已经采样的 custom_id
            for completion in completions:
                sampled_ids.append(completion['task_id'])
                
        # 过滤掉已经采样的数据
        ds_not_enough = [d for d in ds if d['task_id'] not in sampled_ids]
        if len(ds_not_enough)==0:
            logger.info(f'{model_name} No more data to sample.')
            break
    
        openai_completion(ds_not_enough, completions_save_path,save_interval=120,model_name=model_name)
    
if  __name__ == "__main__":
    fire.Fire(main)
