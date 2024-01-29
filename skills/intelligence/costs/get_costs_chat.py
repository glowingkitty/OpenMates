################
# Default Imports
################
import sys
import os
import re

# Fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('skills.intelligence.*', '', full_current_path)
sys.path.append(main_directory)

from server import *
################


def get_costs_chat(
        num_input_tokens: int,
        num_output_tokens: int = None,
        model_name: str = "gpt-4-turbo-preview",
        model_max_output_tokens: int = 4096,
        currency: str = "USD") -> dict:
    try:
        add_to_log(state="start", module_name="LLMs", color="yellow")
        add_to_log(f"Calculating the costs using the {model_name} model...")
        prices_per_token = {
            "gpt-3.5-turbo":{"input": 0.0005/1000, "output": 0.0015/1000},
            "gpt-4-turbo-preview": {"input": 0.01/1000, "output": 0.03/1000},
            "gpt-4-vision-preview": {"input": 0.01/1000, "output": 0.03/1000},
            "mistral-tiny": {"input": 0.14/1000000, "output": 0.42/1000000},
            "mistral-small": {"input": 0.60/1000000, "output": 1.80/1000000},
            "mistral-medium": {"input": 2.50/1000000, "output": 7.50/1000000},
        }
        if model_name == "gpt-3.5":
            model_name = "gpt-3.5-turbo"
        elif model_name == "gpt-4":
            model_name = "gpt-4-turbo-preview"

        # calculate the costs
        input_costs = num_input_tokens * prices_per_token[model_name]["input"]
        output_costs = None
        if num_output_tokens:
            output_costs = num_output_tokens * prices_per_token[model_name]["output"]
            
        
        # if the output costs are not given, estimate them
        if output_costs:
            total_costs = input_costs + output_costs

            add_to_log(state="success", message=f"Successfully calculated the costs for using the {model_name} model:")
            add_to_log(state="success", message=f"Total: {round(total_costs,4)} {currency} (for {num_input_tokens} input tokens and {num_output_tokens} output tokens)")

            return {
                "total_costs": total_costs,
                "currency": currency
                }
        
        else:
            output_costs_min = 5 * prices_per_token[model_name]["output"]
            output_costs_max = model_max_output_tokens * prices_per_token[model_name]["output"]

            total_costs_min = input_costs + output_costs_min
            total_costs_max = input_costs + output_costs_max

            add_to_log(state="success", message=f"Successfully calculated the costs using the {model_name} model:")
            add_to_log(state="success", message=f"Minimum: {round(total_costs_min,4)} {currency}")
            add_to_log(state="success", message=f"Maximum: {round(total_costs_max,4)} {currency}")
            add_to_log(state="success", message=f"For {num_input_tokens} input tokens (and unknown output tokens)")

            return {
                "total_costs_min": total_costs_min,
                "total_costs_max": total_costs_max,
                "currency": currency
                }
    
    except KeyboardInterrupt:
        shutdown()
    
    except Exception:
        process_error(f"Failed getting the cost estimate for '{num_input_tokens}' tokens using the '{model_name}' model.", traceback=traceback.format_exc())
        return None
    

if __name__ == "__main__":
    # test the function with the arguments from the command line
    tokens_used = int(sys.argv[1])

    gpt_3_5_turbo = get_costs_chat(
        num_input_tokens=tokens_used,
        model_name="gpt-3.5-turbo"
    )
    gpt_4_turbo = get_costs_chat(
        num_input_tokens=tokens_used,
        model_name="gpt-4-turbo-preview"
    )
    mistral_medium = get_costs_chat(
        num_input_tokens=tokens_used,
        model_name="mistral-medium"
    )
    mistral_small = get_costs_chat(
        num_input_tokens=tokens_used,
        model_name="mistral-small"
    )

    # compare the costs
    add_to_log("Cost comparison (min costs):")
    add_to_log(f"For {tokens_used} tokens:")
    add_to_log(f"gpt-3.5-turbo: {round(gpt_3_5_turbo['total_costs_min'],4)} {gpt_3_5_turbo['currency']}")
    add_to_log(f"gpt-4-turbo-preview: {round(gpt_4_turbo['total_costs_min'],4)} {gpt_4_turbo['currency']}")
    add_to_log(f"mistral-medium: {round(mistral_medium['total_costs_min'],4)} {mistral_medium['currency']}")
    add_to_log(f"mistral-mistral_small: {round(mistral_small['total_costs_min'],4)} {mistral_medium['currency']}")
