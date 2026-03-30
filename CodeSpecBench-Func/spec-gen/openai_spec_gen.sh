set -e
cd CodeSpecBench/CodeSpecBench-Func

# 循环执行每个模型
# qwen-max-latest qwen-plus-latest qwen-turbo-latest qwen-coder-plus-latest qwen-coder-turbo-latest
# qwen3-32b qwen3-14b qwen3-8b qwq-plus-latest 需要stream模式
for model in  "gpt-5-mini" "claude-sonnet-4-5-20250929" "gemini-2.5-pro" "gemini-2.5-flash" "gpt-oss-120b" "deepseek-v3.2-think" "deepseek-v3.2" "gpt-5-chat-latest"
do
    python ./spec-gen/openai_spec_gen.py $model
done