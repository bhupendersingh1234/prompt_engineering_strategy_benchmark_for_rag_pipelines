from . import zero_shot, few_shot, chain_of_thought, structured_output

STRATEGY_MODULES = {
    "zero_shot": zero_shot,
    "few_shot": few_shot,
    "chain_of_thought": chain_of_thought,
    "structured_output": structured_output,
}
