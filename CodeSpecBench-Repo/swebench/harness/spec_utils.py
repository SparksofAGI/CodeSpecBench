from loguru import logger
import json
from tenacity import retry, stop_after_attempt, wait_random
from openai import OpenAI
from tqdm import tqdm
import re
from collections import defaultdict
from pathlib import Path
import logging
import ast
# Disable HTTPX logging
logging.getLogger("httpx").setLevel(logging.WARNING)

PROMPT="""
Please write a conftest.py file that defines pytest_sessionstart, along with precondition and postcondition functions for this issue. You should import the target function that requires modification, along with any other necessary libraries, then use the pytest_sessionstart hook to wrap this target function. This ensures that when pytest runs, the patch automatically triggers both the precondition and postcondition functions. The precondition and postcondition should verify whether the target function’s behavior aligns with the issue statement after modification. Respond with the complete conftest.py implementation in the following format.
<conftest.py>
import pytest
import chat.utils as utils

def pytest_sessionstart(session):
    original_add = utils.add

    def wrapped_add(num1, num2):
        precondition(num1, num2)
        result = original_add(num1, num2)
        postcondition(num1, num2, result)
        return result

    utils.add = wrapped_add
    
def precondition(num1, num2):
    assert isinstance(num1, (int, float)), "num1 must be int or float"
    assert isinstance(num2, (int, float)), "num2 must be int or float"
    return True

def postcondition(num1, num2, result):
    assert result == num1 + num2, "result must equal num1 + num2"
    return True
</conftest.py>"""

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

@retry(stop=stop_after_attempt(2), wait=wait_random(min=5, max=10))
def openai_model_call(user_prompt,model="gpt-4o-mini"):
    try:
        client = OpenAI(            
            # 其他大模型
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

def replace_prompt(instance_text):
    """
    Replace everything after </code> in instance_text with PROMPT
    """
    if "</code>" in instance_text:
        # Find the position of </code> and keep everything up to and including it
        code_end_index = instance_text.find("</code>") + len("</code>")
        # Replace everything after </code> with PROMPT
        user_prompt = instance_text[:code_end_index] + PROMPT
    # else:
    #     # If </code> is not found, just append PROMPT to the original text
    #     user_prompt = instance_text + PROMPT
    
    return user_prompt

def parse_patch_headers_nearest(patch_text: str):
    """
    将 class/def 头部作为同级“最近声明锚点”。
    规则：
      + <header> → added
      - <header> → removed
      其他 + / - 出现在最近锚点之下 → modified（锚点用完整 header 文本）
    返回：
    {
      "path/to/file.py": {
         "added":    ["class Foo(Bar):", "def bar(self):"],
         "removed":  ["class Old:", ...],
         "modified": ["def y(self):", "class Baz:"]
      }, ...
    }
    """
    
    # 返回完整的class/def 头部
    # 捕获完整的 class/def 头部（含参数/继承，直到冒号），并作为 "header" 返回
    # 例： "class Foo(Bar):" 或 "def y(self, x=1):"

    # 完整头部：优先尝试
    HEADER_LINE_STRICT = re.compile(
        r'^\s*(?P<header>('
        r'class\s+[A-Za-z_]\w*\s*(?:\([^)]*\))?\s*:'
        r'|def\s+[A-Za-z_]\w*\s*\([^)]*\)\s*:'
        r'))'
    )
    HEADER_INLINE_STRICT = re.compile(
        r'(?P<header>('
        r'class\s+[A-Za-z_]\w*\s*(?:\([^)]*\))?\s*:'
        r'|def\s+[A-Za-z_]\w*\s*\([^)]*\)\s*:'
        r'))'
    )

    # 宽松头部：允许缺右括号和冒号（适配被截断的 diff 行）
    HEADER_LINE_LOOSE = re.compile(
        r'^\s*(?P<header>('
        r'class\s+[A-Za-z_]\w*(?:\s*\([^)]*)?'   # 允许 "(" 后未闭合
        r'|def\s+[A-Za-z_]\w*\s*(?:\([^)]*)?'   # 同上
        r'))'
    )
    HEADER_INLINE_LOOSE = re.compile(
        r'(?P<header>('
        r'class\s+[A-Za-z_]\w*(?:\s*\([^)]*)?'
        r'|def\s+[A-Za-z_]\w*\s*(?:\([^)]*)?'
        r'))'
    )

    def match_header_line(content: str):
        m = HEADER_LINE_STRICT.match(content)
        return m.group('header') if m else (HEADER_LINE_LOOSE.match(content).group('header') if HEADER_LINE_LOOSE.match(content) else None)

    def match_header_inline(tail: str):
        m = HEADER_INLINE_STRICT.search(tail)
        return m.group('header') if m else (HEADER_INLINE_LOOSE.search(tail).group('header') if HEADER_INLINE_LOOSE.search(tail) else None)

    def normalize_header(h: str) -> str:
        return re.sub(r'\s+', ' ', h.strip())

    
    results = defaultdict(lambda: {"added": set(), "removed": set(), "modified": set()})
    current_file = None
    last_header = None            # 最近的完整头部文本（标准化）
    hunk_add_or_remove = set()    # 本 hunk 内已经判定为 add/remove 的头部，避免误记 modified

    lines = patch_text.splitlines()

    for line in lines:
        # 文件切换
        if line.startswith('diff --git '):
            current_file = None
            continue
        if line.startswith('+++ '):
            path = line[4:].strip().split('\t', 1)[0]
            if path != '/dev/null':
                if path.startswith(('a/','b/')): path = path[2:]
                current_file = path
            continue
        if line.startswith('--- '):
            path = line[4:].strip().split('\t', 1)[0]
            if current_file is None and path != '/dev/null':
                if path.startswith(('a/','b/')): path = path[2:]
                current_file = path
            continue

        # 新 hunk：尝试从 @@ 尾部解析 class/def 头部作为初始锚点
        if line.startswith('@@'):
            m_tail = re.search(r'@@.*@@\s*(?P<tail>.*)$', line)
            last_header = None
            if m_tail:
                tail = m_tail.group('tail')
                header_raw = match_header_inline(tail)           # @@ 尾部匹配
                if header_raw:
                    last_header = normalize_header(header_raw)
            hunk_add_or_remove = set()
            continue

        if current_file is None:
            continue

        # diff 前缀
        prefix  = line[:1] if line else ''
        content = line[1:] if prefix in ('+','-',' ') else line

        # 1) 这行本身是 class/def 头部：它就是新的“最近锚点”，并按前缀分类
        header_raw = match_header_line(content)          # 行首匹配
        if header_raw:
            header = normalize_header(header_raw)

            if prefix == '+':
                results[current_file]['added'].add(header)
                hunk_add_or_remove.add(header)
            elif prefix == '-':
                results[current_file]['removed'].add(header)
                hunk_add_or_remove.add(header)

            # 不论 + / - / 空格，这个头部都成为“最近锚点”
            last_header = header
            continue

        # 2) 普通变更行：若存在最近锚点，且此锚点不在本 hunk 的 add/remove 集合中，则算 modified
        if prefix in ('+','-') and last_header:
            if last_header not in hunk_add_or_remove:
                results[current_file]['modified'].add(last_header)

    # 去重并排序输出
    out = {}
    for fpath, groups in results.items():
        out[fpath] = {
            'added':    sorted(groups['added']),
            'removed':  sorted(groups['removed']),
            'modified': sorted(groups['modified']),
        }
    return out

def extract_conftest(raw_conftest):
    """
    Extract content between <conftest.py> and </conftest.py> tags
    """
    # First, remove content between <think> tags if they exist
    # QWQ推理结果没有<think>
    if raw_conftest.find("</think>") != -1:
        # Remove the entire <pytest> section including the tags
        end_idx = raw_conftest.find("</think>") + len("</think>")
        raw_conftest = raw_conftest[end_idx:]
    # 找到所有 <conftest.py> ... </conftest.py> 包裹的内容
    pattern = r"<conftest\.py>\s*([\s\S]*?)\s*</conftest\.py>"
    find_completions = re.findall(pattern, raw_conftest, flags=re.IGNORECASE)

    if find_completions:
        # 找出内容最长的那个代码块
        longest = max(find_completions, key=lambda x: len(x.strip()))

        # 再额外处理代码块标记
        # 如果以```python开头，去掉开头的```python
        if longest.strip().startswith("```python"):
            # 查找第一个```python的出现位置
            start_idx = longest.find("```python")
            if start_idx != -1:
                # 移动到```python之后
                longest = longest[start_idx + len("```python"):]
        
        # 如果以```结尾，去掉结尾的```
        longest = longest.rstrip()  # 先去掉末尾空白字符
        if longest.endswith("```"):
            longest = longest[:-3]
        
        # 去掉可能的多余空白字符
        longest = longest.strip()

        return longest
    # 没找到conftest.py标记，尝试找```python代码块
    else:
        # 找到所有代码块包裹内容
        pattern = r"```python\s*([\s\S]*?)\s*```"
        find_completions = re.findall(pattern, raw_conftest)
        
        if find_completions:
            # 找出内容最长的那个代码块
            longest = max(find_completions, key=lambda x: len(x.strip()))
            return longest
        else:
            return None

def debug_print_conftest(conftest):
    lines = conftest.split("\n")
    new_lines = []

    inside_func_header = False
    pending_insert = None   # 存储等待插入的内容

    for line in lines:
        stripped = line.strip()

        # 判断是否函数头开始
        if stripped.startswith("def precondition"):
            inside_func_header = True
            pending_insert = "print('!!!!!!!!!!!!!!!!!!!this is precondition!!!!!!!!!!!!!!!!!!!')"
            indent = " " * (len(line) - len(line.lstrip()))

        elif stripped.startswith("def postcondition"):
            inside_func_header = True
            pending_insert = "print('!!!!!!!!!!!!!!!!!!!this is postcondition!!!!!!!!!!!!!!!!!!!')"
            indent = " " * (len(line) - len(line.lstrip()))

        elif stripped.startswith("def pytest_sessionstart"):
            inside_func_header = True
            pending_insert = "print('!!!!!!!!!!!!!!!!!!!this is pytest_sessionstart!!!!!!!!!!!!!!!!!!!')"
            indent = " " * (len(line) - len(line.lstrip()))

        new_lines.append(line)

        # 如果当前正在函数头，并且这一行是函数头结束（以 “:” 结尾）
        if inside_func_header and stripped.endswith(":"):
            new_lines.append(indent + "    " + pending_insert)
            inside_func_header = False
            pending_insert = None

    return "\n".join(new_lines)


def format_file_headers_dict_to_string(changes_dict):
    """
    将变更字典按照指定格式转换为字符串
    
    Args:
        changes_dict: 包含文件变更信息的字典，格式为：
            {
                'file_path': {
                    'added': [added_lines],
                    'removed': [removed_lines], 
                    'modified': [modified_lines]
                }
            }
    
    Returns:
        str: 格式化后的字符串
    """
    lines = []
    
    for file_path, changes in changes_dict.items():
        lines.append(f"File: {file_path}")
        
        # 处理新增的内容
        if changes.get('added'):
            lines.append("  ADD:")
            for item in changes['added']:
                lines.append(f"    - {item}")
        
        # 处理删除的内容  
        if changes.get('removed'):
            lines.append("  REMOVE:")
            for item in changes['removed']:
                lines.append(f"    - {item}")
        
        # 处理修改的内容
        if changes.get('modified'):
            lines.append("  MODIFY:")
            for item in changes['modified']:
                lines.append(f"    - {item}")
        
        # 文件之间添加空行分隔（除了最后一个文件）
        if file_path != list(changes_dict.keys())[-1]:
            lines.append("")
    
    return "\n".join(lines)
def add_hints_prompt(user_prompt,patch):
    """
    add hints to user_prompt
    """
    file_headers_dict=parse_patch_headers_nearest(patch)
    file_headers_str=format_file_headers_dict_to_string(file_headers_dict)
    sep_idx=user_prompt.find('Respond with the complete conftest.py implementation in the following format')
    return user_prompt[:sep_idx]+'\n'+'Hints:\n'+ file_headers_str +'\n\n'+user_prompt[sep_idx:]
    
def django_process_conftest(code_string):
    # 删除 import pytest
    code_string = re.sub(r'^import pytest\s*$', '', code_string, flags=re.MULTILINE)
    
    # 查找所有包含django的import语句
    django_imports = []
    lines = code_string.split('\n')
    new_lines = []
    
    i = 0
    sessionstart_found = False
    
    while i < len(lines):
        line = lines[i]
        
        # 检查是否遇到了函数定义
        if re.match(r'^\s*def\s+\w+\(', line):
            sessionstart_found = True
            
        # 如果已经遇到了函数定义，直接添加剩余行并退出循环
        if sessionstart_found:
            new_lines.extend(lines[i:])
            break
        
        # 检查是否是以from或import开头且包含django的行
        if re.match(r'^\s*(from|import)\s+.*django', line):
            # 收集完整的import语句（可能跨多行）
            import_block = [line]
            
            # 检查是否开始了多行import（有未闭合的括号）
            j = i + 1
            open_parentheses = line.count('(') - line.count(')')
            
            # 继续收集直到所有括号都闭合
            while j < len(lines) and open_parentheses > 0:
                import_block.append(lines[j])
                open_parentheses += lines[j].count('(') - lines[j].count(')')
                j += 1
            
            # 如果是以反斜杠结束，继续收集下一行
            while j < len(lines) and import_block[-1].rstrip().endswith('\\'):
                import_block.append(lines[j])
                j += 1
            
            # 将完整的import语句保存
            django_imports.extend(import_block)
            i = j  # 跳过已处理的行
        else:
            new_lines.append(line)
            i += 1
    
    # 重新构建代码
    code_string = '\n'.join(new_lines)
    
    # 在pytest_sessionstart函数内部插入django imports
    if django_imports:
        # 找到pytest_sessionstart函数定义
        sessionstart_match = re.search(r'(def pytest_sessionstart\(session\):\s*\n)', code_string)
        if sessionstart_match:
            indent = '    ' # 增加一级缩进
            django_imports_code = '\n'.join([f'{indent}{imp}' for imp in django_imports])
            
            # 在函数开始处插入imports
            insertion_point = sessionstart_match.end(1)
            code_string = (code_string[:insertion_point] + 
                          django_imports_code + '\n\n' + 
                          code_string[insertion_point:])
    # 将 def pytest_sessionstart(session): 替换为 def setup_test_environment():
    code_string = re.sub(r'def pytest_sessionstart\(session\):', 'def setup_test_environment():', code_string)
    return code_string

def django_insert_setup(code_string):
    """
    使用AST分析在指定函数的return语句前插入setup_test_environment()
    """
    # 解析代码为AST
    tree = ast.parse(code_string)
    
    # 遍历AST查找目标函数
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in ['setup', 'setup_run_tests']:
            # 查找函数中的return语句
            for i, stmt in enumerate(node.body):
                if isinstance(stmt, ast.Return):
                    # 在return语句前插入函数调用
                    indent = ' ' * 4  # 假设4空格缩进
                    call_line = f"{indent}setup_test_environment()"
                    
                    # 将代码分割成行
                    lines = code_string.split('\n')
                    
                    # 找到return语句的行号
                    return_lineno = stmt.lineno - 1  # AST行号从1开始
                    
                    # 在return语句前插入新行
                    lines.insert(return_lineno, call_line)
                    return '\n'.join(lines)

def django_process_runtests(original_runtests,conftest,log_dir):
    # 更改为django_conftest格式，将import语句移入函数内，改变函数头
    django_conftest=django_process_conftest(conftest)
    
    # 在runtests.py中找到setup或setup_run_tests函数定义位置，插入conftest内容
    target_pattern = r"^def (?P<func_name>setup|setup_run_tests)\s*\("
    # 使用搜索和替换
    match = re.search(target_pattern, original_runtests, flags=re.MULTILINE)
    if match:
        runtests_wconftest = original_runtests.replace(match.group(0), django_conftest + '\n\n' + match.group(0))
        Path(log_dir / "runtests_wconftest.py").write_text(runtests_wconftest)
    # 插入setup_test_environment()调用
    runtests_wconftest_nsetup=django_insert_setup(runtests_wconftest)
    Path(log_dir / "runtests.py").write_text(runtests_wconftest_nsetup)

    return runtests_wconftest_nsetup

def llm_conftest_generation(instance,model,log_dir):
    # Check if llm_conftest.py already exists
    if Path(log_dir / "llm_conftest.py").exists():
        # Read existing conftest file
        raw_conftest = Path(log_dir / "llm_conftest.py").read_text()
        # logger.info("Found existing conftest file")
    else:
        # Call model if file doesn't exist
        # 构造prompt
        user_prompt=replace_prompt(instance['text'])
        user_prompt=add_hints_prompt(user_prompt,instance['patch'])
        Path(log_dir / "user_prompt.md").write_text(user_prompt)
        # 调用模型
        response=openai_model_call(user_prompt,model)
        raw_conftest=response.choices[0].message.content
        Path(log_dir / "llm_conftest.py").write_text(raw_conftest)

    # 提取conftest
    conftest=extract_conftest(raw_conftest)
    debug_conftest=debug_print_conftest(conftest)
    Path(log_dir / "llm_conftest_final.py").write_text(debug_conftest)
    
    # 静态检查
    tree = ast.parse(debug_conftest)
    return debug_conftest

def wrap_functions_with_tryexcept(code,log_dir):
    """
    用于检查spec的completeness，将pre，origin，post包裹上try，except。
    """
    lines = code.splitlines()
    out = []
    i = 0
    n = len(lines)

    def indent_of(line: str) -> int:
        return len(line) - len(line.lstrip())

    def starts_wrapp_def(line: str) -> bool:
        return re.match(r'\s*def\s+wrapp\w*\s*\(', line) is not None

    def is_pre_start(stripped: str) -> bool:
        return stripped.startswith("precondition")

    def is_post_start(stripped: str) -> bool:
        return stripped.startswith("postcondition")

    def is_origin_assign_start(stripped: str) -> bool:
        # result = origin...( 或 result = original...( 皆可
        return re.match(r'^result\s*=\s*(origin|original)\w*\s*\(', stripped) is not None

    def is_origin_call_start(stripped: str) -> bool:
        # origin...( 或 original...( 皆可
        return re.match(r'^(origin|original)\w*\s*\(', stripped) is not None

    def should_collect_multiline(stmt_lines: list[str]) -> bool:
        """只要这一句出现了 '(' 且还没配平，就继续收集"""
        s = "\n".join(stmt_lines)
        return "(" in s

    def paren_balance_ignoring_strings(s: str) -> int:
        """
        计算 s 中括号净余额：'(' +1, ')' -1
        忽略单引号/双引号/三引号里的括号（做一个实用版，不追求100% Python 语法完备）
        """
        bal = 0
        in_single = False
        in_double = False
        in_triple_single = False
        in_triple_double = False
        escape = False

        i = 0
        while i < len(s):
            ch = s[i]

            if escape:
                escape = False
                i += 1
                continue

            if ch == "\\":
                escape = True
                i += 1
                continue

            # 处理三引号切换
            if not (in_single or in_double):
                if s.startswith("'''", i) and not in_triple_double:
                    in_triple_single = not in_triple_single
                    i += 3
                    continue
                if s.startswith('"""', i) and not in_triple_single:
                    in_triple_double = not in_triple_double
                    i += 3
                    continue

            if in_triple_single:
                i += 1
                continue
            if in_triple_double:
                i += 1
                continue

            # 处理单/双引号切换
            if ch == "'" and not in_double:
                in_single = not in_single
                i += 1
                continue
            if ch == '"' and not in_single:
                in_double = not in_double
                i += 1
                continue

            if in_single or in_double:
                i += 1
                continue

            if ch == "(":
                bal += 1
            elif ch == ")":
                bal -= 1

            i += 1

        return bal

    def collect_statement(start_idx: int, base_indent: int) -> tuple[list[str], int]:
        """
        从 start_idx 开始收集“一个语句”的行（主要用于多行函数调用）。
        规则：
        - 先从起始行开始
        - 若括号余额>0，继续收集后续行直到余额回到0
        - 若遇到缩进回退到 <= base_indent 且该行非空，认为离开 wrapp 函数块（停止）
        返回：收集到的行列表、下一个未消费的索引
        """
        stmt = [lines[start_idx]]
        idx = start_idx + 1

        # 快速判断：如果没有 '(' 就当单行
        if not should_collect_multiline(stmt):
            return stmt, idx

        bal = paren_balance_ignoring_strings(stmt[0])
        while idx < n and bal > 0:
            nxt = lines[idx]
            # 如果函数体结束（缩进回退），也要停（避免越界到下一个 def）
            if nxt.strip() and indent_of(nxt) <= base_indent:
                break
            stmt.append(nxt)
            bal += paren_balance_ignoring_strings(nxt)
            idx += 1

        return stmt, idx

    def emit_try_block(ind: str, stmt_lines: list[str], kind: str, has_result: bool):
        """
        kind: 'pre'/'post'/'origin'
        has_result: origin/original 是否是 result = xxx
        """
        if kind == "pre":
            msg = "precondition function failed"
            raise_line = f"{ind}    raise"
            except_tail = [f"{ind}except:", f"{ind}    print('{msg}')", raise_line]
        elif kind == "post":
            msg = "postcondition function failed"
            raise_line = f"{ind}    raise"
            except_tail = [f"{ind}except:", f"{ind}    print('{msg}')", raise_line]
        else:
            msg = "original function failed"
            if has_result:
                except_tail = [f"{ind}except:", f"{ind}    print('{msg}')", f"{ind}    result = None"]
            else:
                except_tail = [f"{ind}except:", f"{ind}    print('{msg}')"]

        out.append(f"{ind}try:")
        # try 内部语句：保持原有多行结构，但整体缩进 +4
        for j, raw in enumerate(stmt_lines):
            # 去掉原本的左侧缩进，再加上 try 内缩进
            out.append(f"{ind}    {raw.lstrip()}")
        out.extend(except_tail)

    while i < n:
        line = lines[i]
        out.append(line)

        if starts_wrapp_def(line):
            base_indent = indent_of(line)
            i += 1

            while i < n:
                curr = lines[i]
                curr_indent = indent_of(curr)

                # wrapp 函数结束
                if curr.strip() and curr_indent <= base_indent:
                    break

                stripped = curr.strip()

                # precondition 多行收集
                if is_pre_start(stripped):
                    stmt_lines, next_i = collect_statement(i, base_indent)
                    ind = " " * curr_indent
                    emit_try_block(ind, stmt_lines, kind="pre", has_result=False)
                    i = next_i
                    continue

                # postcondition 多行收集
                if is_post_start(stripped):
                    stmt_lines, next_i = collect_statement(i, base_indent)
                    ind = " " * curr_indent
                    emit_try_block(ind, stmt_lines, kind="post", has_result=False)
                    i = next_i
                    continue

                # result = origin/original 多行收集
                if is_origin_assign_start(stripped):
                    stmt_lines, next_i = collect_statement(i, base_indent)
                    ind = " " * curr_indent
                    emit_try_block(ind, stmt_lines, kind="origin", has_result=True)
                    i = next_i
                    continue

                # origin/original 普通调用 多行收集
                if is_origin_call_start(stripped):
                    stmt_lines, next_i = collect_statement(i, base_indent)
                    ind = " " * curr_indent
                    emit_try_block(ind, stmt_lines, kind="origin", has_result=False)
                    i = next_i
                    continue

                # 其他行原样输出
                out.append(curr)
                i += 1

            continue

        i += 1

    wrapped_conftest="\n".join(out)
    Path(log_dir / "llm_conftest_final_complete.py").write_text(wrapped_conftest)
    return "\n".join(out)
