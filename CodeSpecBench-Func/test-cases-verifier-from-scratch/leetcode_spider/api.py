from .error import Reach429
import json
import requests as rq
from tenacity import retry, stop_after_attempt, wait_exponential
from loguru import logger
from requests.exceptions import Timeout
# 集合了各类leetcode api
def get_preset_code(lc_client, slug, lang='python3'):
    url = "https://leetcode.cn/graphql/"
    payload_template = r"""{"query":"\n    query questionEditorData($titleSlug: String!) {\n  question(titleSlug: $titleSlug) {\n    questionId\n    questionFrontendId\n    codeSnippets {\n      lang\n      langSlug\n      code\n    }\n    envInfo\n    enableRunCode\n    hasFrontendPreview\n    frontendPreviews\n  }\n}\n    ","variables":{"titleSlug":"shortest-bridge"},"operationName":"questionEditorData"}"""
    payload_template = json.loads(payload_template)
    payload_template['variables']['titleSlug'] = slug
    payload = json.dumps(payload_template).encode('utf-8')
    result = lc_client.client.post(url, data=payload, headers=lc_client.headers, verify=False).json()
    # print(result)
    editor_datas = result['data']['question']['codeSnippets']
    if editor_datas is None: # or slug ==  'binary-tree-upside-down':
        a=2

    # 代码完善：增加对不同语言的支持
    key_certain = None
    # print(editor_datas)
    for key in range(editor_datas.__len__()):
        if editor_datas[key]['lang'].lower() == lang.lower():
            key_certain = key
    # [3]['code']
    if key_certain is None:
        editor_code = ''
    else:
        editor_code = editor_datas[key_certain]['code']

    return result, editor_code

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=3, max=20))
def get_real_qid(lc_client, slug, grahql_url="https://leetcode.cn/graphql/"):
    """"""
    payload_template = r"""{"query":"\n    query questionTitle($titleSlug: String!) {\n  question(titleSlug: $titleSlug) {\n    questionId\n    questionFrontendId\n    title\n    titleSlug\n    isPaidOnly\n    difficulty\n    likes\n    dislikes\n    categoryTitle\n  }\n}\n    ","variables":{"titleSlug":"convert-binary-search-tree-to-sorted-doubly-linked-list"},"operationName":"questionTitle"}"""
    payload_template = json.loads(payload_template)
    payload_template["variables"]["titleSlug"] = slug
    payload = json.dumps(payload_template).encode('utf8')
    result = lc_client.client.post('https://leetcode.cn/graphql/', data=payload, headers=lc_client.headers,
                                   verify=False)
    try:
        result = result.json()
        qid = result['data']['question']['questionId']
        difficulty = result['data']['question']['difficulty']
        return qid, difficulty, result
    
    except Exception as e:
        print(f'{type(e).__name__}: {e}')
        raise e

def submit(lc_client, qid, code, lang, submit_url):
    payload_template = r"""{"lang":"python3","question_id":"1","typed_code":"class Solution:\n    def twoSum(self, nums: List[int], target: int) -> List[int]:\n        print(5)"}"""
    payload_template = json.loads(payload_template)
    # print('len of code', payload_template['typed_code'].__len__())
    payload_template['lang'] = lang
    payload_template['question_id'] = str(qid)
    payload_template['typed_code'] = code
    payload_template = json.dumps(payload_template).encode('utf8')
    # print(payload_template)
    lc_client.headers['Content-Length'] = ""
    # lc_client.headers['Referer'] = ''
    submit_result = lc_client.client.post(submit_url, headers=lc_client.headers, data=payload_template,
                                          verify=False)  # .json()
    # submit_result.status_code=429 
    if submit_result.status_code == 429:
        Reach429.cnt_429 += 1
    if Reach429.cnt_429 > 0:
        raise Reach429()
    try:
        submit_result = submit_result.json()
    except Exception as e:
        print("submit函数遇到json错误")
        print("submit url:", submit_url)
        print(submit_result.status_code)
        print(submit_result.text)
        print("payload value: ", payload_template)

        raise e
    return submit_result


def get_submission_details(lc_client, sid):
    payload_template = r"""{"query":"\n    query submissionDetails($submissionId: ID!) {\n  submissionDetail(submissionId: $submissionId) {\n    code\n    timestamp\n    statusDisplay\n    isMine\n    runtimeDisplay: runtime\n    memoryDisplay: memory\n    memory: rawMemory\n    lang\n    langVerboseName\n    question {\n      questionId\n      titleSlug\n      hasFrontendPreview\n    }\n    user {\n      realName\n      userAvatar\n      userSlug\n    }\n    runtimePercentile\n    memoryPercentile\n    submissionComment {\n      flagType\n    }\n    passedTestCaseCnt\n    totalTestCaseCnt\n    fullCodeOutput\n    testDescriptions\n    testInfo\n    testBodies\n    ... on GeneralSubmissionNode {\n      outputDetail {\n        codeOutput\n        expectedOutput\n        input\n        compileError\n        runtimeError\n        lastTestcase\n      }\n    }\n  }\n}\n    ","variables":{"submissionId":"493346313"},"operationName":"submissionDetails"}"""
    payload_template = json.loads(payload_template)
    payload_template['variables']['submissionId'] = str(sid)
    # details = post('https://leetcode.cn/graphql/', payload_template)
    payload_template = json.dumps(payload_template).encode('utf8')
    details = lc_client.client.post('https://leetcode.cn/graphql/', data=payload_template, headers=lc_client.headers,
                                    verify=False)  # .json()
    try:
        details = details.json()
    except Exception as e:
        print("获取提交结果时遇到错误")
        print("payload value : ", payload_template)
        print(details.status_code)
        print(details.text)
        raise e

    return details


def get_question_content(lc_client, slug):
    payload_template = r"""{"query":"\n    query questionContent($titleSlug: String!) {\n  question(titleSlug: $titleSlug) {\n    content\n    editorType\n    mysqlSchemas\n    dataSchemas\n  }\n}\n    ","variables":{"titleSlug":"longest-palindromic-substring"},"operationName":"questionContent"}"""
    payload_template = json.loads(payload_template)
    payload_template['variables']['titleSlug'] = slug
    payload_template = json.dumps(payload_template).encode('utf8')
    details = lc_client.client.post('https://leetcode.cn/graphql/', data=payload_template, headers=lc_client.headers,
                                    verify=False)  # .json()
    try:
        details = details.json()
        content = details['data']['question']['content']
    except Exception as e:
        print("获取Content结果时遇到错误")
        print("payload value : ", payload_template)
        print(details.status_code)
        print(details.text)
        raise e

    return details, content


def get_question_translation(lc_client, slug):
    payload_template = r"""{"query":"\n    query questionTranslations($titleSlug: String!) {\n  question(titleSlug: $titleSlug) {\n    translatedTitle\n    translatedContent\n  }\n}\n    ","variables":{"titleSlug":"longest-palindromic-substring"},"operationName":"questionTranslations"}"""
    payload_template = json.loads(payload_template)
    payload_template['variables']['titleSlug'] = slug
    payload_template = json.dumps(payload_template).encode('utf8')
    details = lc_client.client.post('https://leetcode.cn/graphql/', data=payload_template, headers=lc_client.headers,
                                    verify=False)  # .json()
    try:
        details = details.json()
        content = details['data']['question']['translatedContent']
        translated_title = details['data']['question']['translatedTitle']
    except Exception as e:
        print("获取Translated Content结果时遇到错误")
        print("payload value : ", payload_template)
        print(details.status_code)
        print(details.text)
        raise e

    return details, content, translated_title


def get_questions_list_100(lc_client, start_num, cookie=None):
    payload_template = r"""{"query":"\n    query problemsetQuestionList($categorySlug: String, $limit: Int, $skip: Int, $filters: QuestionListFilterInput) {\n  problemsetQuestionList(\n    categorySlug: $categorySlug\n    limit: $limit\n    skip: $skip\n    filters: $filters\n  ) {\n    hasMore\n    total\n    questions {\n      acRate\n      difficulty\n      freqBar\n      frontendQuestionId\n      isFavor\n      paidOnly\n      solutionNum\n      status\n      title\n      titleCn\n      titleSlug\n      topicTags {\n        name\n        nameTranslated\n        id\n        slug\n      }\n      extra {\n        hasVideoSolution\n        topCompanyTags {\n          imgUrl\n          slug\n          numSubscribed\n        }\n      }\n    }\n  }\n}\n    ","variables":{"categorySlug":"all-code-essentials","skip":3150,"limit":100,"filters":{}},"operationName":"problemsetQuestionList"}"""
    payload_template = json.loads(payload_template)
    payload_template['variables']['skip'] = start_num
    payload_template = json.dumps(payload_template).encode('utf8')

    rq_headers = lc_client.headers
    if cookie is not None:
        rq_headers['Cookie'] = cookie
    details = lc_client.client.post('https://leetcode.cn/graphql/', data=payload_template, headers=rq_headers,
                                    verify=False)  # .json()
    try:
        details = details.json()
        content_list = details['data']['problemsetQuestionList']['questions']
    except Exception as e:
        print("获取题目列表结果时遇到错误")
        print("payload value : ", payload_template)
        print(details.status_code)
        print(details.text)
        raise e
    return details, content_list
@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=10, max=20))
def invoke_interpret_solution(lc_client, slug, testcases, question_id, code, lang='python3', cookie=None):
    payload_template = r"""{"lang":"python3","question_id":"415","typed_code":"class Solution:\n    def addStrings(self, num1: str, num2: str) -> str:\n        return 0\n        ","data_input":"\"11\"\n\"123\"\n\"456\"\n\"77\"\n\"0\"\n\"0\""}"""
    payload_template = json.loads(payload_template)
    payload_template['data_input'] = testcases
    payload_template['lang'] = lang
    payload_template['question_id'] = question_id
    payload_template['typed_code'] = code
    payload_template = json.dumps(payload_template).encode('utf8')
    invoke_url = f'https://leetcode.cn/problems/{slug}/interpret_solution/'

    rq_headers = lc_client.headers
    if cookie is not None:
        rq_headers['Cookie'] = cookie

    try:
        details = lc_client.client.post(invoke_url, data=payload_template, headers=rq_headers,verify=False, timeout=100)  
        details = details.json()
        exp_id = details['interpret_expected_id']
        run_id = details['interpret_id']
        return details, exp_id, run_id, None, True
    
    except Timeout:
        logger.warning(f"{slug} 请求超时，跳过")
        return None, None, None, dict(run_success=False, runtime_error='请求超时100s', status_code=None), True
    
    except Exception as e:
        if 'error' in details:
            logger.warning(f"提交失败：slug:{slug}\n details:{details}")
            print_cookie=lc_client.client.cookies.get(' _ga_PDVPZYN3CW')
            logger.warning(f"print_cookie:{print_cookie}")
            return details, None, None, None, False
        
        # 重试
        elif details.status_code == 429:
            logger.info(f'{slug} 429,try again')
            raise e
        
        elif details.status_code == 413:
            logger.warning(f'负载过重：slug:{slug}\n len(test_input_params):{len(testcases)}')
            return details, None, None, dict(run_success=False, runtime_error=details.text, status_code=413), True
        
        else:
            logger.warning(f'提交失败：slug:{slug}\n details:{details}')
            return details, None, None, None, False
    
@retry(stop=stop_after_attempt(10), wait=wait_exponential(multiplier=3, min=5, max=10))
def invoke_check(lc_client, run_id, cookie=None):
    invoke_url = f'https://leetcode.cn/submissions/detail/{run_id}/check/'
    rq_headers = lc_client.headers
    if cookie is not None:
        rq_headers['Cookie'] = cookie
    details = lc_client.client.post(invoke_url, headers=rq_headers,verify=False)  # .json()

    details = details.json()
    if not len(details.keys()) > 1:
        raise
    return details
    

