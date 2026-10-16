"""Offline planning arithmetic; never a production tariff or inferred cache hit.

Run from this directory or the repository root. --matrix emits the scenarios
used in scenarios.csv. Financial inputs are optional, in USD consistently.
Requires the repository's PyYAML dependency; performs no provider/network calls.
"""

import argparse
import csv
import sys
from decimal import Decimal, localcontext
from fractions import Fraction as F
from pathlib import Path

import yaml


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
MILLION = 1_000_000


def show(value):
    if value is None:
        return "unverified"
    with localcontext() as context:
        context.prec = 30
        return format(Decimal(value.numerator) / Decimal(value.denominator), ".6f")


def charge(value):
    """Existing contract: aggregate first, floor once, then minimum one."""
    return max(1, value.numerator // value.denominator)


def ceil(value):
    return -(-value.numerator // value.denominator)


def model_config():
    design = yaml.safe_load((HERE / "implementation-design.yml").read_text())
    for model in design["representative_models"]:
        provider = yaml.safe_load(
            (ROOT / "backend/providers" / model["provider_file"]).read_text()
        )
        configured = next(item for item in provider["models"] if item["id"] == model["id"])
        rates = configured["pricing"]["tokens"]
        assert rates["input"]["per_credit_unit"] == model["input_tokens_per_credit"]
        assert rates["output"]["per_credit_unit"] == model["output_tokens_per_credit"]
        input_cost = F(model["supplier_input"])
        read_cost = F(model["supplier_read"])
        assert F(model["proposed_read_tokens_per_credit"]) == (
            model["input_tokens_per_credit"] * input_cost / read_cost
        )
        if model["proposed_write_tokens_per_credit"] is not None:
            assert F(model["proposed_write_tokens_per_credit"]) == (
                model["input_tokens_per_credit"] * input_cost / F(model["supplier_write"])
            )
    return design["representative_models"]


def simulate(model, input_tokens, output_tokens, prefix_fraction, calls, hit_after_first, share, financial):
    prefix = input_tokens * prefix_fraction.numerator // prefix_fraction.denominator
    if model["id"] == "mistral-large-4":
        prefix = prefix // 64 * 64
    if prefix < model["minimum_prefix_tokens"]:
        prefix = 0
    ordinary = input_tokens - prefix
    input_credit = F(1, model["input_tokens_per_credit"])
    output_credit = F(1, model["output_tokens_per_credit"])
    input_cost = F(model["supplier_input"])
    read_cost = F(model["supplier_read"])
    output_cost = F(model["supplier_output"])
    paid_write = model["supplier_write"] is not None
    write_cost = F(model["supplier_write"]) if paid_write else input_cost
    read_weight = 1 - share * (1 - read_cost / input_cost)
    baseline_raw = input_tokens * input_credit + output_tokens * output_credit
    public_write_weight = (
        write_cost / input_cost
        if model["proposed_write_tokens_per_credit"] is not None
        else F(1)
    )
    first_raw = (ordinary + prefix * public_write_weight) * input_credit + output_tokens * output_credit
    warm_raw = (ordinary + prefix * read_weight) * input_credit + output_tokens * output_credit
    baseline_cost = F(input_tokens, MILLION) * input_cost + F(output_tokens, MILLION) * output_cost
    first_cost = F(ordinary, MILLION) * input_cost + F(prefix, MILLION) * write_cost + F(output_tokens, MILLION) * output_cost
    warm_cost = F(ordinary, MILLION) * input_cost + F(prefix, MILLION) * read_cost + F(output_tokens, MILLION) * output_cost
    later_raw = warm_raw if hit_after_first else first_raw
    later_cost = warm_cost if hit_after_first else first_cost
    baseline = charge(baseline_raw)
    first = charge(first_raw)
    later = charge(later_raw)
    total = first + (calls - 1) * later
    baseline_total = calls * baseline
    provider_total = first_cost + (calls - 1) * later_cost
    row = {
        "model": model["id"], "read_savings_share": show(share),
        "input_tokens": input_tokens, "output_tokens": output_tokens,
        "reusable_prefix_tokens": prefix, "calls": calls,
        "later_calls_report_hits": hit_after_first,
        "uncached_reference_credits": baseline,
        "first_request_credits": first, "later_request_credits": later,
        "total_reference_credits": baseline_total, "total_proposed_credits": total,
        "later_saving_percent": show(F(100) * (1 - F(later, baseline))),
        "total_saving_percent": show(F(100) * (1 - F(total, baseline_total))),
        "supplier_total_usd": show(provider_total),
    }
    if financial is None:
        row.update({"margin_status": "unverified", "minimum_required_total_credits": "unverified"})
    else:
        net_value, margin, minimum, overhead = financial
        costs = [first_cost + overhead] + [later_cost + overhead] * (calls - 1)
        floors = [ceil(max(cost / (1 - margin), cost + minimum) / net_value) for cost in costs]
        charges = [first] + [later] * (calls - 1)
        row.update({
            "margin_status": "passes supplied assumptions" if all(a >= b for a, b in zip(charges, floors)) else "fails supplied assumptions; recalibrate before activation",
            "minimum_required_total_credits": sum(floors),
        })
    assert prefix + ordinary == input_tokens
    assert first_cost >= baseline_cost
    assert warm_cost <= baseline_cost
    assert calls == 1 or hit_after_first or later == first
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matrix", action="store_true")
    parser.add_argument("--input", type=int, default=100_000)
    parser.add_argument("--output", type=int, default=1_000)
    parser.add_argument("--prefix-fraction", type=F, default=F("0.8"))
    parser.add_argument("--calls", type=int, default=10)
    parser.add_argument("--read-savings-share", type=F, default=F(1))
    parser.add_argument("--no-later-hits", action="store_true")
    parser.add_argument("--net-usd-per-credit", type=F)
    parser.add_argument("--target-margin", type=F)
    parser.add_argument("--minimum-contribution-usd", type=F)
    parser.add_argument("--other-cost-usd-per-call", type=F)
    args = parser.parse_args()
    financial = (args.net_usd_per_credit, args.target_margin, args.minimum_contribution_usd, args.other_cost_usd_per_call)
    if any(value is not None for value in financial):
        if any(value is None for value in financial):
            parser.error("Provide all four financial inputs, consistently in USD.")
        if financial[0] <= 0 or not 0 <= financial[1] < 1 or min(financial[2:]) < 0:
            parser.error("Invalid financial inputs.")
    else:
        financial = None
    if not 1 <= args.input <= 200_000 or not 0 <= args.output <= 30_000:
        parser.error("This ordinary-context illustration supports 1..200000 input and 0..30000 output.")
    if not 0 <= args.prefix_fraction <= 1 or not 0 <= args.read_savings_share <= 1 or args.calls < 1:
        parser.error("Fractions must be 0..1 and calls positive.")
    scenarios = [("custom", args.input, args.output, args.prefix_fraction, args.calls, not args.no_later_hits)]
    shares = [args.read_savings_share]
    if args.matrix:
        shares = [F(1), F("0.5")]
        scenarios = [
            ("input_heavy_80pct", 100_000, 1_000, F("0.8"), 10, True),
            ("input_heavy_50pct", 100_000, 1_000, F("0.5"), 10, True),
            ("first_call_only", 100_000, 1_000, F("0.8"), 1, True),
            ("expired_every_call", 100_000, 1_000, F("0.8"), 10, False),
            ("output_heavy", 10_000, 3_000, F("0.5"), 10, True),
            ("short_prompt", 500, 100, F("0.8"), 10, True),
        ]
    rows = []
    for model in model_config():
        for share in shares:
            for name, inputs, outputs, prefix, calls, hit in scenarios:
                rows.append({"scenario": name, **simulate(model, inputs, outputs, prefix, calls, hit, share, financial)})
    writer = csv.DictWriter(sys.stdout, fieldnames=list(rows[0]), lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)


if __name__ == "__main__":
    main()
