set -e

cd CodeSpecBench/CodeSpecBench-Repo

for model_name in "gemini-2.5-flash" "gemini-2.5-pro" "deepseek-v3.2" "claude-sonnet-4-5-20250929" "gpt-5-chat-latest" "gpt-5-mini" "gpt-oss-120b" "deepseek-v3.2-think"
do
    python -m swebench.harness.chatgpt_api_inference \
        --model_name "${model_name}"
done
