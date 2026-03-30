set -e
cd CodeSpecBench/CodeSpecBench-Func/spec-verifier

# "gpt-oss-120b" "gpt-5-mini" "claude-sonnet-4-5-20250929" "gemini-2.5-pro" "gemini-2.5-flash" "deepseek-v3.2-think" "deepseek-v3.2" "gpt-5-chat-latest" 
# "Qwen3-0.6B" "Qwen3-1.7B" "Qwen3-4B" "Qwen3-14B" "Qwen3-32B" "QwQ-32B"

for model_name in "gpt-oss-20b" "Qwen3-0.6B-thinking" "Qwen3-1.7B-thinking" "Qwen3-4B-thinking" "Qwen3-14B-thinking" "Qwen3-32B-thinking" "QwQ-32B-thinking"
do
    python evaluate_functional_correctness.py ../spec-gen/sample_results/$model_name.jsonl
done
