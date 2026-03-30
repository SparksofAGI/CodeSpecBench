from utils import append_jsonl,read_jsonl,read_jsonl_gz
from time import time,sleep
import os,json
import argparse
from vllm import LLM, SamplingParams
from transformers import AutoTokenizer
from tqdm import tqdm
import fire
from loguru import logger

with open('./PROMPT_TEMPLATE.txt','r') as f:
    PROMPT_TEMPLATE=f.read()

def single_mode_completion(ds,completions_save_path, model_path,device_ids):  
    tokenizer = AutoTokenizer.from_pretrained(model_path)

    messages=[]
    for d in ds:
        user_prompt = PROMPT_TEMPLATE.format(PROBLEM_DESCRIPTION=d['problem_description'])
        message = [{"role": "user", "content": user_prompt}]
        text = tokenizer.apply_chat_template(
            message,
            tokenize=False,
            add_generation_prompt=True
        )
        messages.append(text)
    logger.info(f'Processing {len(messages)} datasets...')
    
    os.environ["CUDA_VISIBLE_DEVICES"] = ','.join(map(str, device_ids))
    logger.info(f'os.environ["CUDA_VISIBLE_DEVICES"] is {os.environ["CUDA_VISIBLE_DEVICES"]}')
    
    sampling_params = SamplingParams(max_tokens=32768)
    llm = LLM(model=model_path,disable_custom_all_reduce=True,tensor_parallel_size=len(device_ids))
    
    
    outputs = llm.generate(messages,sampling_params)

    completions=[]
    for output_idx,output in enumerate(outputs):
        generated_text = output.outputs[0].text
        completions.append(dict(
            task_id=ds[output_idx]['task_id'],
            completion=generated_text,
        ))

    append_jsonl(completions, completions_save_path)
def main(model_name,gpu_ids):  
    while True:
        ds=read_jsonl_gz('./data/CodeSpecBench.jsonl.gz')

        completions_save_path=f'./spec-gen/sample_results/{model_name}.jsonl'
        model_path=f'{model_name}'
        
        completions = []
        sampled_ids = []
        # 跳过已经采样的
        if os.path.exists(completions_save_path):
            completions = read_jsonl(completions_save_path)
            
            # 拿出已经采样的 custom_id
            for completion in completions:
                sampled_ids.append(completion['task_id'])
                
        # 过滤掉已经采样的数据
        ds_not_enough = [d for d in ds if d['task_id'] not in sampled_ids]
        if len(ds_not_enough)==0:
            logger.info('No more data to sample.')
            break
        
        single_mode_completion(ds_not_enough,completions_save_path, model_path,gpu_ids)

if  __name__ == "__main__":
    logger.add('./spec-gen/vllm_spec_gen.log')
    # os.environ["VLLM_WORKER_MULTIPROC_METHOD"] = "spawn"
    fire.Fire(main)