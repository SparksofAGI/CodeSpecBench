import os, random,shutil,re,json, gzip, ast
from tqdm import tqdm
import numpy as np
import pandas as pd
from datasets import load_dataset
from transformers import AutoConfig, AutoTokenizer, AutoModelForCausalLM
import concurrent.futures
from time import time,sleep
import requests as requests
from openai import OpenAI
from tenacity import retry, stop_after_attempt, wait_exponential
from loguru import logger
from func_timeout import func_set_timeout

def load_dataset_from_file_or_folder(file_folder_path):
    # 给定的路径是目录，从文件夹中加载parquet文件
    ds=None
    if os.path.isdir(file_folder_path):
        parquet_files=[]
        for filepath,dirnames,filenames in os.walk(file_folder_path):
            for filename in filenames:
                if filename.endswith('parquet'):
                    fullname = os.path.join(filepath, filename)
                    parquet_files.append(fullname)
        ds = load_dataset("parquet", data_files=parquet_files)['train']

    # 给定的路径是文件名，从文件中加载parquet文件
    elif os.path.isfile(file_folder_path):
        ds = load_dataset("parquet", data_files=file_folder_path)['train']
        
    # 可能没有添加parquet，添加了再load
    elif not file_folder_path.endswith('parquet'):
        print('尝试添加parquet后缀')
        ds=load_dataset_from_file_or_folder(file_folder_path+'.parquet')
        
    if ds is None:
        raise Exception(f'check the dataset path: {file_folder_path}')
    else:
        logger.info("file_folder_path reading is finished. lines: {}\t . Path: {}".format(len(ds), file_folder_path))
        return ds


def set_seed(seed):
    os.environ['PYTHONHASHSEED'] = str(seed)
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed(seed)
        torch.cuda.manual_seed_all(seed)

def post_process_and_save(args,text_out,funit,sc_ba,prompt_i,sol_name,save_dir):
    """
    text_out shape[0] 是为multi-sample准备的，对于贪婪采样，目前是1 
    """
    post_process_text_out=[]

    for text in text_out:
        # 将补全的函数体尾巴切干净
        text_truncate = brace_truncate(text)
        post_process_text_out.append(text_truncate)

    #replace the origin function as the generated one in the contract.
    for text_id,text in enumerate(post_process_text_out):
        # 返回函数注释和函数头，以{结尾，没有换行符
        half_funit=truncate_funit(funit)
        funit_completion=f'{half_funit}\r\n{text}'
        sc_before=sc_ba[0]
        sc_after=sc_ba[1]
        replaces=f'{sc_before}\r\n{funit_completion}\r\n{sc_after}'

        #save generated smart contracts
        sc_save=f'{args.model_name}_epoch{args.ckpt_id}_prompt{prompt_i}_sample{text_id}'
        sc_save_dir=os.path.join(save_dir,'test',sc_save)
        os.makedirs(sc_save_dir,exist_ok=True)
        with open(os.path.join(sc_save_dir,sol_name.split('/')[-1]),'w') as f:
            f.write(replaces)
    
    #save generated functions
    fn_save_dir=os.path.join(save_dir,'sample_functions')
    os.makedirs(fn_save_dir,exist_ok=True)
    fn_sample_save=f'{fn_save_dir}/{args.model_name}_epoch{args.ckpt_id}_prompt{prompt_i}.txt'
    with open(fn_sample_save,'w') as f:
        f.write(f'funit:\n\n{funit}\n\n')
        for i,text in enumerate(post_process_text_out):
            f.write(f'out[{i+1}]:\n\n{half_funit}\r\n{text}\n\n')


def save_list_of_dir_as_parquet(list_of_dir,parquet_file_path):
    """
    # 把list of dir文件存为parquet，通过pandas
    """
    directory=os.path.dirname(parquet_file_path)
    if not os.path.exists(directory):
        os.makedirs(directory, exist_ok=True)
        print(f"Directory created: {directory}")
    df = pd.DataFrame(list_of_dir)
    df.to_parquet(parquet_file_path, engine='pyarrow')
    print(f'Save to {parquet_file_path}')
    

def read_jsonl(file_path):
    """
    读取JSON Lines文件
    返回list of json loads
    会跳过空行
    如果中间有错会报错位置并且继续加载
    """
    data = []
    with open(file_path, 'r', encoding='utf-8') as f:
        for line_number, line in enumerate(f):
            line = line.strip()
            if not line:
                continue
            try:
                data.append(json.loads(line))
            except json.JSONDecodeError as e:
                logger.warning(f"{file_path} JSON decode error on line {line_number + 1}: {e}")
                continue
    logger.info("Jsonl reading is finished. lines: {}\t . Path: {}".format(len(data), file_path))
    return data

def write_jsonl(list_of_dict,file_path):
    """
    写入JSON Lines文件
    会根据 file_path 创建目录
    """
    assert isinstance(list_of_dict, list), "list_of_dict 应该是一个 list 类型"
    directory=os.path.dirname(file_path)
    if not os.path.exists(directory):
        os.makedirs(directory, exist_ok=True)
    with open(file_path, 'w') as file:
        for item in list_of_dict:
            json.dump(item, file)
            file.write('\n')
    logger.info("Jsonl writing is finished. lines: {}\t . Path: {}".format(len(list_of_dict), file_path))

def model_call(messages):
    """
    openai chatgpt使用，默认模型是gpt-4o-mini，换模型需要在utils文件更换，输入是整个messages
    """
    model=["gpt-4o-mini","gpt-3.5-turbo",'gpt-4o'][0]
    client = OpenAI(
        api_key=''
    )
    
    completions = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=0,
    )            
    print(completions.choices[0].message.content)        
    return completions


def ohmygpt_model_call(messages,model_name):
    api_key = ""

    headers = {
        "Authorization": 'Bearer ' + api_key,
    }

    params = {
        "messages": messages,
        "model": model_name,
        # "temperature": 0,
    }
    
    response = requests.post(
        "",
        headers=headers,
        json=params,
        stream=False
    )
    
    res = response.json()
    # res_content = res['choices'][0]['message']['content']
    # print(res_content)
    return res

def call_with_retry(messages, max_attempts=3,model_name='gpt-4o-mini'):
    attempt = 0
    while attempt < max_attempts:
        try:
            # 调用模型
            completions = ohmygpt_model_call(messages,model_name)
            return completions  # 如果成功，返回结果
        
        except Exception as e:
            attempt += 1
            print(f"Attempt {attempt} failed: {e}")
            if attempt == max_attempts:
                print("Max attempts reached. Failed to get a response.")
                raise  # 如果达到最大尝试次数，重新抛出异常
            else:
                sleep(10)

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=10, max=10))
def read_jsonl_gz(file_path):
    try:
        ds=[]
        with gzip.open(file_path, 'rt', encoding='utf-8') as f:
            for line in f:
                data = json.loads(line.strip())
                ds.append(data)
        logger.info("jsonl.gz reading is finished. lines: {}\t . Path: {}".format(len(ds), file_path))
        return ds
    except EOFError as e:
        logger.error(f"Try again... Error: {e}")
        raise e
    except Exception as e:
        logger.error(f"An error occurred: {e}")
        return None
def write_jsonl_gz(list_of_dict,file_path):
    assert isinstance(list_of_dict, list), "list_of_dict 应该是一个 list 类型"
    directory=os.path.dirname(file_path)
    if not os.path.exists(directory):
        os.makedirs(directory, exist_ok=True)
        
    with gzip.open(file_path, "wt", encoding="utf-8") as f:
        for item in list_of_dict:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
    logger.info("jsonl.gz writing is finished. lines: {}\t . Path: {}".format(len(list_of_dict), file_path))

# @retry(stop=stop_after_attempt(1), wait=wait_exponential(multiplier=1, min=1, max=20))
# @func_set_timeout(100)  # 设置200秒超时
def openai_model_call(user_prompt,model="gpt-4o-mini"):
    try:
        client = OpenAI(

            base_url='',
            api_key=''  
        )
        completion = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": user_prompt}],
        )
    except Exception as e:
        tqdm.write(str(e))
        raise e
    # print(completion.choices[0].message)
    return completion
def append_jsonl(list_of_dict, file_path):
    """
    将一个 JSON 对象追加写入到指定的 JSONL 文件中。

    :param file_path: str - JSONL 文件的路径
    :param data_list: List[dict] - 要写入的 JSON 数据列表，每个元素是一个字典
    会判断jsonl文件是不是换行符\n结尾，如果没有则添加
    """
    assert isinstance(list_of_dict, list), "list_of_dict 应该是一个 list 类型"
    directory=os.path.dirname(file_path)
    if not os.path.exists(directory):
        os.makedirs(directory, exist_ok=True)
        
    # 判断文件是否存在
    file_exists = os.path.isfile(file_path) and os.path.getsize(file_path) > 0

    # 检查最后一个字符是否为换行符
    needs_newline = False
    if file_exists:
        with open(file_path, 'rb') as f:
            try:
                f.seek(-1, os.SEEK_END)
                last_char = f.read(1)
                if last_char != b'\n':
                    needs_newline = True
            except OSError:
                # 文件为空或无法读取（如空文件）
                needs_newline = False

    with open(file_path, 'a', encoding='utf-8') as f:
        if needs_newline:
            f.write('\n')
            
    with open(file_path, 'a', encoding='utf-8') as f:
        for item in list_of_dict:
            json_line = json.dumps(item, ensure_ascii=False)
            f.write(json_line + '\n')
    logger.info("Jsonl appending is finished. lines: {}\t . Path: {}".format(len(list_of_dict), file_path))

def build_testcase_string_for_submit(testcases):
    result = []
    for item in testcases:
        # Safely parse the item instead of using eval
        item_string_listform=f"[{item}]"
        item_list = ast.literal_eval(item_string_listform)
        item_string = '\n'.join(repr(i).replace("'", '"') for i in item_list)
        result.append(item_string)
    return '\n'.join(result)

def return_test_input_params(test_input):
    """
    test_input是指preconditions()
    """
    def is_valid_expression(expr_str):
        try:
            # mode='eval' 表示只允许表达式，不允许语句（如赋值、if 等）
            ast.parse(expr_str, mode='eval')
            return True
        except (SyntaxError, TypeError, MemoryError) as e:
            return e

    def extract_bracket_content(s):
        """
        返回字符串中第一个括号对之间的内容（基于第一个 '(' 和最后一个 ')'）
        """
        # 查找第一个左括号 '('
        start_idx = s.find('(')
        if start_idx == -1:
            # print("未找到左括号 '('")
            return None

        # 查找最后一个右括号 ')'
        end_idx = s.rfind(')')
        if end_idx == -1:
            # print("未找到右括号 ')'")
            return None

        # 确保右括号在左括号之后
        if end_idx <= start_idx:
            # print("括号顺序错误")
            return None

        # 返回括号内的内容
        return s[start_idx + 1:end_idx]
    
    # 存在括号没有闭合的情况
    if 'was never closed' in str(is_valid_expression(test_input)):
        return None
    # 存在注释的情况
    test_input_params=extract_bracket_content(test_input)
    return test_input_params

def openai_completion_process(completion):
    # 找到所有代码块包裹内容
    pattern = r"```python\s*([\s\S]*?)```"
    find_completions = re.findall(pattern, completion)

    if not find_completions:
        return None  # 或者抛出异常、返回空字符串等，根据你的需求调整

    # 找出内容最长的那个代码块
    longest = max(find_completions, key=lambda x: len(x.strip()))

    return longest

def verify_test_input(test_input,params_num):
    # 验证输入是否符合要求
    test_input_params=return_test_input_params(test_input)
    if test_input_params==None:
        return False
    try:
        testcase_string=build_testcase_string_for_submit([test_input_params])
    except Exception as e:
        return False
    if testcase_string == '':
        return False
    if testcase_string.count('\n')!=params_num-1:
        return False
    return True