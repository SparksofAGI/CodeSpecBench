from swebench.harness.spec_utils import replace_prompt,add_hints_prompt,read_jsonl
import fire
from tqdm import tqdm
from time import sleep
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from openai import OpenAI

def openai_model_call(user_prompt,model):
    client = OpenAI(            
        # 其他大模型
        base_url='',
        api_key=''     
    )
    completion = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": user_prompt}],
    )
    return completion

def llm_conftest_generation(instance,model,log_dir):
    # Check if llm_conftest.py already exists
    if Path(log_dir / "llm_conftest.py").exists():
        return True
    else:
        # Call model if file doesn't exist
        # 构造prompt
        user_prompt=replace_prompt(instance['text'])
        user_prompt=add_hints_prompt(user_prompt,instance['patch'])
        # Path(log_dir / "user_prompt.md").write_text(user_prompt)
        # 调用模型
        try:
            response=openai_model_call(user_prompt,model)
            raw_conftest=response.choices[0].message.content
            print('YES')
        except Exception as e:
            tqdm.write(str(e))
            # 超出上下文长度
            # if 'input characters limit' in str(e) or 'input token limit' in str(e):
            # 不同模型报错不一样
            if 'Error code: 400' in str(e):
                raw_conftest=""
            else:
                return False
        Path(log_dir / "llm_conftest.py").parent.mkdir(parents=True, exist_ok=True)
        Path(log_dir / "llm_conftest.py").write_text(raw_conftest)
        return True

def openai_completion(swe_bench_verified,model_name):
    
    # 控制速率为 100 RPM, 超过会超速率
    rate_limit = 50 / 60  # 转换为每秒的请求数
    delay = 1 / rate_limit

    # 使用 ThreadPoolExecutor 进行并发调用
    with ThreadPoolExecutor(max_workers=1) as executor:
        futures = []
        for instance in tqdm(swe_bench_verified, total=len(swe_bench_verified),desc=f"{model_name} Submitting tasks"):
            log_dir=Path(f'SpecCodeBench/SpecCodeBench-Repo/logs/sample_results/{model_name}/{instance["instance_id"]}')
            
            future = executor.submit(llm_conftest_generation, instance, model_name, log_dir)
            futures.append(future)
            # sleep(delay)  # 控制速率

        for future in tqdm(as_completed(futures), total=len(futures), desc=f"{model_name} Completing tasks"):
            completion = future.result()
    
def main(model_name):
    swe_bench_verified=read_jsonl('SpecCodeBench/SpecCodeBench-Repo/SpecCodeBench-Repo.jsonl')
    
    while True:
        # 将还没sample的提出来
        swe_bench_verified_not_sample=[]
        for instance in swe_bench_verified:
            log_dir=Path(f'SpecCodeBench/SpecCodeBench-Repo//logs/sample_results/{model_name}/{instance["instance_id"]}')
            if not Path(log_dir / "llm_conftest.py").exists():
                swe_bench_verified_not_sample.append(instance)
                
        if swe_bench_verified_not_sample:
            # swe_bench_verified_not_sample=swe_bench_verified_not_sample[:3]
            openai_completion(swe_bench_verified_not_sample,model_name)
            # tqdm.write(f"Processing {len(swe_bench_verified_not_sample)} instances for {model_name}...")
            # break
        else:
            tqdm.write(f"All instances for {model_name} have been processed.")
            break
        
        
if __name__ == "__main__":
    fire.Fire(main)