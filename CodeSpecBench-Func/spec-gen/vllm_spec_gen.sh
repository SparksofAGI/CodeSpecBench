set -e
cd CodeSpecBench/CodeSpecBench-Func

# 循环执行每个模型
for model in DeepSeek_R1_Distill_Qwen_1p5B DeepSeek_R1_Distill_Qwen_7B DeepSeek_R1_Distill_Qwen_14B DeepSeek_R1_Distill_Llama_8B
do
    python ./spec-gen/vllm_spec_gen.py $model 0,1
done