# backend/apps/math/skills/calculate_skill.py
#
# Math Calculate skill — accurate numeric and symbolic computation.
#
# Uses sympy for symbolic algebra (simplification, equation solving, derivatives,
# integrals) and mpmath for high-precision numerical evaluation. This guarantees
# mathematically correct results that LLMs cannot reliably produce on their own.
#
# Supported modes (auto-detected or explicitly set via 'mode' parameter):
#   numeric   — Evaluate expression to a decimal number (e.g. "cos(pi/4)")
#   symbolic  — Return exact symbolic form (e.g. "sqrt(2)/2")
#   solve     — Solve equation for a variable (e.g. "solve(x^2 - 4*x + 3, x)")
#   simplify  — Algebraic simplification (e.g. "simplify((x^2-1)/(x-1))")
#   diff      — Derivative (e.g. "diff(sin(x)*exp(x), x)")
#   integrate — Indefinite/definite integral (e.g. "integrate(x^2, x)")
#   convert   — Unit conversion (e.g. "convert(100, kg, lbs)")
#   auto      — Detect mode from expression (default)
#
# Architecture: Direct async execution in app-math container (no Celery worker).
# sympy operations are generally fast (<1s). CPU-bound: runs in a thread pool
# via asyncio.run_in_executor to avoid blocking the event loop.

import logging
import asyncio
import re
from typing import Any, Dict, List, Optional, Tuple
from pydantic import BaseModel, Field

from backend.apps.base_skill import BaseSkill

logger = logging.getLogger(__name__)


# ── Request / Response models ─────────────────────────────────────────────────

class CalculateRequest(BaseModel):
    """
    Request model for the math calculate skill.
    Matches tool_schema in app.yml.
    """
    expression: str = Field(
        ...,
        description="Mathematical expression, equation, or operation to evaluate"
    )
    mode: str = Field(
        default="auto",
        description="Evaluation mode: auto, numeric, symbolic, solve, simplify, diff, integrate, convert"
    )
    variable: str = Field(
        default="x",
        description="Variable to differentiate/integrate with respect to, or solve for"
    )
    precision: int = Field(
        default=15,
        ge=1,
        le=100,
        description="Number of significant digits for numeric results"
    )


class CalculateStep(BaseModel):
    """One step in a symbolic calculation chain."""
    description: str = Field(..., description="Human-readable description of this step")
    latex: str = Field(..., description="LaTeX representation of this step's result")


class CalculateResponse(BaseModel):
    """
    Response model for the math calculate skill.
    
    Fields (internal names):
    - expression_latex: The input expression formatted as LaTeX
    - result_latex:     The result formatted as LaTeX (symbolic or numeric)
    - result_numeric:   Floating-point approximation (None for purely symbolic results)
    - result_str:       Human-readable string of the result
    - steps:            Optional step-by-step breakdown (for solve/diff/integrate)
    - mode_used:        Which evaluation mode was actually applied
    - error:            Error message if computation failed
    
    When serialized for the frontend embed (via model_dump()), the short field names
    are used so the frontend MathCalculateEmbedPreview can read them directly:
    - expression_latex → expression
    - result_str       → result
    - mode_used        → mode
    These match the CalculateResult interface in MathCalculateEmbedPreview.svelte.
    """
    expression_latex: str = Field(default="", description="Input expression as LaTeX")
    result_latex: str = Field(default="", description="Result as LaTeX")
    result_numeric: Optional[float] = Field(None, description="Numeric approximation")
    result_str: str = Field(default="", description="Human-readable result string")
    steps: List[CalculateStep] = Field(default_factory=list, description="Calculation steps")
    mode_used: str = Field(default="auto", description="Evaluation mode actually applied")
    error: Optional[str] = Field(None, description="Error message if computation failed")

    def model_dump(self, **kwargs: Any) -> Dict[str, Any]:  # type: ignore[override]
        """
        Override model_dump to output short field names expected by the frontend.
        
        The frontend MathCalculateEmbedPreview reads:
          results[0].expression  (not expression_latex)
          results[0].result      (not result_str)
          results[0].mode        (not mode_used)
        
        We keep the long-form fields too so nothing downstream breaks if it reads them.
        """
        base = super().model_dump(**kwargs)
        base["expression"] = base.get("expression_latex", "")
        base["result"] = base.get("result_str", "")
        base["mode"] = base.get("mode_used", "auto")
        return base


# ── Unit conversion table ─────────────────────────────────────────────────────
# Maps unit names to (quantity_type, conversion_to_SI) pairs.
# SI base: meter, kilogram, second, kelvin, mole
_UNIT_MAP: Dict[str, Tuple[str, float]] = {
    # Length
    "m": ("length", 1.0), "meter": ("length", 1.0), "meters": ("length", 1.0),
    "km": ("length", 1000.0), "kilometer": ("length", 1000.0), "kilometers": ("length", 1000.0),
    "cm": ("length", 0.01), "centimeter": ("length", 0.01), "centimeters": ("length", 0.01),
    "mm": ("length", 0.001), "millimeter": ("length", 0.001), "millimeters": ("length", 0.001),
    "mi": ("length", 1609.344), "mile": ("length", 1609.344), "miles": ("length", 1609.344),
    "ft": ("length", 0.3048), "foot": ("length", 0.3048), "feet": ("length", 0.3048),
    "in": ("length", 0.0254), "inch": ("length", 0.0254), "inches": ("length", 0.0254),
    "yd": ("length", 0.9144), "yard": ("length", 0.9144), "yards": ("length", 0.9144),
    "nm": ("length", 1e-9), "nanometer": ("length", 1e-9), "nanometers": ("length", 1e-9),
    "um": ("length", 1e-6), "micrometer": ("length", 1e-6), "micrometers": ("length", 1e-6),
    "au": ("length", 1.495978707e11), "lightyear": ("length", 9.461e15), "ly": ("length", 9.461e15),
    # Mass
    "kg": ("mass", 1.0), "kilogram": ("mass", 1.0), "kilograms": ("mass", 1.0),
    "g": ("mass", 0.001), "gram": ("mass", 0.001), "grams": ("mass", 0.001),
    "mg": ("mass", 1e-6), "milligram": ("mass", 1e-6), "milligrams": ("mass", 1e-6),
    "lbs": ("mass", 0.453592), "lb": ("mass", 0.453592), "pound": ("mass", 0.453592), "pounds": ("mass", 0.453592),
    "oz": ("mass", 0.0283495), "ounce": ("mass", 0.0283495), "ounces": ("mass", 0.0283495),
    "t": ("mass", 1000.0), "ton": ("mass", 1000.0), "tonne": ("mass", 1000.0),
    "st": ("mass", 6.35029), "stone": ("mass", 6.35029),
    # Speed
    "mph": ("speed", 0.44704), "kph": ("speed", 1/3.6), "kmh": ("speed", 1/3.6),
    "m/s": ("speed", 1.0), "ms": ("speed", 1.0), "knot": ("speed", 0.514444), "knots": ("speed", 0.514444),
    # Temperature (special: not simple multiplication)
    "c": ("temperature", None), "celsius": ("temperature", None),
    "f": ("temperature", None), "fahrenheit": ("temperature", None),
    "k": ("temperature", None), "kelvin": ("temperature", None),
    # Area
    "m2": ("area", 1.0), "sqm": ("area", 1.0),
    "km2": ("area", 1e6), "sqkm": ("area", 1e6),
    "ha": ("area", 10000.0), "hectare": ("area", 10000.0), "hectares": ("area", 10000.0),
    "ft2": ("area", 0.092903), "sqft": ("area", 0.092903),
    "acre": ("area", 4046.86), "acres": ("area", 4046.86),
    # Volume
    "l": ("volume", 0.001), "liter": ("volume", 0.001), "liters": ("volume", 0.001),
    "ml": ("volume", 1e-6), "milliliter": ("volume", 1e-6), "milliliters": ("volume", 1e-6),
    "m3": ("volume", 1.0), "gal": ("volume", 0.00378541), "gallon": ("volume", 0.00378541), "gallons": ("volume", 0.00378541),
    "fl oz": ("volume", 2.95735e-5), "floz": ("volume", 2.95735e-5), "cup": ("volume", 0.000236588),
    "pt": ("volume", 0.000473176), "pint": ("volume", 0.000473176), "qt": ("volume", 0.000946353), "quart": ("volume", 0.000946353),
    # Energy
    "j": ("energy", 1.0), "joule": ("energy", 1.0), "joules": ("energy", 1.0),
    "kj": ("energy", 1000.0), "kjoul": ("energy", 1000.0),
    "cal": ("energy", 4.184), "calorie": ("energy", 4.184), "calories": ("energy", 4.184),
    "kcal": ("energy", 4184.0), "kilocalorie": ("energy", 4184.0),
    "wh": ("energy", 3600.0), "kwh": ("energy", 3.6e6),
    "ev": ("energy", 1.60218e-19), "electronvolt": ("energy", 1.60218e-19),
    # Power
    "w": ("power", 1.0), "watt": ("power", 1.0), "watts": ("power", 1.0),
    "kw": ("power", 1000.0), "mw": ("power", 1e6), "hp": ("power", 745.7),
    # Pressure
    "pa": ("pressure", 1.0), "pascal": ("pressure", 1.0),
    "kpa": ("pressure", 1000.0), "mpa": ("pressure", 1e6),
    "bar": ("pressure", 1e5), "atm": ("pressure", 101325.0),
    "psi": ("pressure", 6894.76), "mmhg": ("pressure", 133.322),
    # Data
    "b": ("data", 1.0), "byte": ("data", 1.0), "bytes": ("data", 1.0),
    "kb": ("data", 1000.0), "mb": ("data", 1e6), "gb": ("data", 1e9), "tb": ("data", 1e12),
    "kib": ("data", 1024.0), "mib": ("data", 1024**2), "gib": ("data", 1024**3), "tib": ("data", 1024**4),
    "bit": ("data", 0.125), "bits": ("data", 0.125),
}


def _convert_temperature(value: float, from_unit: str, to_unit: str) -> float:
    """Convert temperature between Celsius, Fahrenheit, and Kelvin."""
    from_unit = from_unit.lower().strip("°")
    to_unit = to_unit.lower().strip("°")
    
    # Convert to Kelvin first
    if from_unit in ("c", "celsius"):
        k = value + 273.15
    elif from_unit in ("f", "fahrenheit"):
        k = (value - 32) * 5 / 9 + 273.15
    elif from_unit in ("k", "kelvin"):
        k = value
    else:
        raise ValueError(f"Unknown temperature unit: {from_unit}")
    
    # Convert from Kelvin to target
    if to_unit in ("c", "celsius"):
        return k - 273.15
    elif to_unit in ("f", "fahrenheit"):
        return (k - 273.15) * 9 / 5 + 32
    elif to_unit in ("k", "kelvin"):
        return k
    else:
        raise ValueError(f"Unknown temperature unit: {to_unit}")


def _do_convert(expression: str) -> Tuple[str, Optional[float], str, str]:
    """
    Parse and execute a unit conversion.
    Supported syntax:
      convert(100, kg, lbs)
      100 kg to lbs
      100kg in lbs
    
    Returns: (result_str, result_numeric, from_unit_display, to_unit_display)
    """
    # Try: convert(value, from, to) syntax
    m = re.match(
        r'^convert\s*\(\s*([+-]?[\d.,eE]+)\s*,\s*([^\s,)]+)\s*,\s*([^\s,)]+)\s*\)$',
        expression.strip(), re.IGNORECASE
    )
    if m:
        value = float(m.group(1).replace(",", ""))
        from_unit = m.group(2).lower()
        to_unit = m.group(3).lower()
    else:
        # Try: "100 kg to lbs" or "100kg in lbs" or "100 kg → lbs"
        m2 = re.match(
            r'^([+-]?[\d.,eE]+)\s*([a-z/²³μ]+[\d]?)\s+(?:to|in|into|→|->)\s+([a-z/²³μ]+[\d]?)$',
            expression.strip(), re.IGNORECASE
        )
        if not m2:
            raise ValueError(
                "Unrecognized conversion syntax. Use: convert(100, kg, lbs) or '100 kg to lbs'"
            )
        value = float(m2.group(1).replace(",", ""))
        from_unit = m2.group(2).lower()
        to_unit = m2.group(3).lower()
    
    # Special case: temperature
    from_entry = _UNIT_MAP.get(from_unit)
    to_entry = _UNIT_MAP.get(to_unit)
    
    if from_entry and from_entry[0] == "temperature":
        result = _convert_temperature(value, from_unit, to_unit)
        result_str = f"{value} {from_unit} = {result:.6g} {to_unit}"
        return result_str, result, from_unit, to_unit
    
    if not from_entry:
        raise ValueError(f"Unknown unit '{from_unit}'")
    if not to_entry:
        raise ValueError(f"Unknown unit '{to_unit}'")
    
    from_type, from_factor = from_entry
    to_type, to_factor = to_entry
    
    if from_type != to_type:
        raise ValueError(
            f"Cannot convert '{from_unit}' ({from_type}) to '{to_unit}' ({to_type})"
        )
    
    # Convert: value * from_factor / to_factor
    result = value * from_factor / to_factor  # type: ignore[operator]
    result_str = f"{value} {from_unit} = {result:.6g} {to_unit}"
    return result_str, result, from_unit, to_unit


def _detect_mode(expression: str) -> str:
    """
    Heuristically detect the evaluation mode from the expression string.
    Returns one of: numeric, symbolic, solve, simplify, diff, integrate, convert.
    """
    expr_lower = expression.lower().strip()
    
    # Explicit function calls
    if re.match(r'^\s*convert\s*\(', expr_lower) or re.search(r'\b(to|in|into)\b.+(kg|lbs|km|miles|mph|celsius|fahrenheit|kelvin|gallons?|liters?)\b', expr_lower, re.IGNORECASE):
        return "convert"
    if re.match(r'^\s*(solve|roots?)\s*\(', expr_lower):
        return "solve"
    if re.match(r'^\s*simplify\s*\(', expr_lower):
        return "simplify"
    if re.match(r'^\s*diff(erentiate)?\s*\(', expr_lower):
        return "diff"
    if re.match(r'^\s*int(egrate)?\s*\(', expr_lower):
        return "integrate"
    
    # Equation: contains "=" not "==" 
    # (LLMs sometimes write "solve x^2 + x - 6 = 0")
    if re.search(r'(?<!=)=(?!=)', expression) and '==' not in expression:
        return "solve"
    
    # Contains symbolic variables (letters that aren't units or functions)
    # Simple heuristic: if there are standalone alphabetic characters not part of
    # known functions, treat as symbolic
    known_funcs = {
        'sin', 'cos', 'tan', 'asin', 'acos', 'atan', 'sinh', 'cosh', 'tanh',
        'exp', 'log', 'ln', 'sqrt', 'abs', 'floor', 'ceil', 'round',
        'pi', 'e', 'inf', 'oo', 'i',
    }
    tokens = re.findall(r'[a-zA-Z]+', expression)
    has_var = any(t.lower() not in known_funcs for t in tokens)
    
    if has_var:
        return "symbolic"
    return "numeric"


def _sympy_compute(
    expression: str,
    mode: str,
    variable: str,
    precision: int,
) -> Tuple[str, str, Optional[float], List[Dict[str, str]], str, str]:
    """
    Perform the actual sympy computation (synchronous, runs in thread pool).
    
    Returns:
        (expression_latex, result_latex, result_numeric, steps, result_str, mode_used)
    
    Raises:
        ValueError: For invalid expressions or unsupported operations.
        Exception:  For unexpected sympy errors.
    """
    # Lazy import — sympy is large; only loaded when the skill actually runs
    import sympy  # noqa: PLC0415
    from sympy import (  # noqa: PLC0415
        sympify, latex, Symbol, N, solve, simplify, diff, integrate,
        expand, factor, cancel,
        pi, E, I, oo,
        sin, cos, tan, asin, acos, atan, atan2,
        sinh, cosh, tanh, asinh, acosh, atanh,
        exp, log, sqrt, Abs, floor, ceiling,
    )
    from sympy.parsing.sympy_parser import (  # noqa: PLC0415
        parse_expr, standard_transformations, implicit_multiplication_application,
    )
    from mpmath import mp  # noqa: PLC0415
    
    # Set mpmath precision
    mp.dps = precision
    
    # Detect mode if auto
    mode_used = mode if mode != "auto" else _detect_mode(expression)
    
    # ── Unit conversion ────────────────────────────────────────────────────────
    if mode_used == "convert":
        result_str, result_numeric, from_unit, to_unit = _do_convert(expression)
        return (
            expression,        # expression_latex — plain text is fine here
            result_str,        # result_latex
            result_numeric,
            [],                # steps
            result_str,        # result_str
            mode_used,
        )
    
    # ── Parse transformations for natural math syntax ──────────────────────────
    transformations = standard_transformations + (implicit_multiplication_application,)
    
    # Normalise common notation quirks before parsing
    expr_clean = expression.strip()
    # Replace ^ with ** for sympy (^ means XOR in Python)
    expr_clean = re.sub(r'\^', '**', expr_clean)
    # Replace "where x=5, y=3" style substitutions
    subs: Dict[Any, Any] = {}
    where_match = re.search(r'\bwhere\b(.+)$', expr_clean, re.IGNORECASE)
    if where_match:
        expr_clean = expr_clean[:where_match.start()].strip()
        for part in where_match.group(1).split(','):
            lhs_rhs = part.split('=')
            if len(lhs_rhs) == 2:
                sym_name = lhs_rhs[0].strip()
                sym_val = lhs_rhs[1].strip()
                try:
                    subs[Symbol(sym_name)] = sympify(sym_val)
                except Exception:
                    pass
    
    # Sympy local namespace — maps common names to sympy objects
    local_ns: Dict[str, Any] = {
        'pi': pi, 'e': E, 'E': E, 'i': I, 'I': I, 'oo': oo, 'inf': oo,
        'sin': sin, 'cos': cos, 'tan': tan,
        'asin': asin, 'acos': acos, 'atan': atan, 'atan2': atan2,
        'sinh': sinh, 'cosh': cosh, 'tanh': tanh,
        'asinh': asinh, 'acosh': acosh, 'atanh': atanh,
        'exp': exp, 'log': log, 'ln': log, 'sqrt': sqrt,
        'abs': Abs, 'Abs': Abs, 'floor': floor, 'ceil': ceiling, 'ceiling': ceiling,
        'solve': solve, 'simplify': simplify, 'diff': diff, 'integrate': integrate,
        'expand': expand, 'factor': factor, 'cancel': cancel,
    }
    
    var_sym = Symbol(variable)
    
    steps: List[Dict[str, str]] = []
    result_sym: Any = None
    result_numeric: Optional[float] = None
    
    # ── Solve mode ────────────────────────────────────────────────────────────
    if mode_used == "solve":
        # Parse: might be "solve(expr, x)" or just "expr = 0" or "LHS = RHS"
        m_solve_call = re.match(r'^\s*(solve|roots?)\s*\((.+)\)\s*$', expr_clean, re.IGNORECASE)
        if m_solve_call:
            inner = m_solve_call.group(2).strip()
            # Check if variable is explicitly specified: solve(expr, x)
            var_match = re.match(r'^(.+),\s*([a-zA-Z_]\w*)\s*$', inner)
            if var_match:
                eq_expr = var_match.group(1).strip()
                var_sym = Symbol(var_match.group(2).strip())
            else:
                eq_expr = inner
        else:
            # Treat whole expression as equation/expression to solve
            eq_expr = expr_clean
        
        # Handle "LHS = RHS" — convert to LHS - RHS = 0
        eq_match = re.match(r'^(.+?)(?<!=)=(?!=)(.+)$', eq_expr)
        if eq_match:
            lhs_str = eq_match.group(1).strip()
            rhs_str = eq_match.group(2).strip()
            try:
                lhs = parse_expr(lhs_str, local_dict=local_ns, transformations=transformations)
                rhs = parse_expr(rhs_str, local_dict=local_ns, transformations=transformations)
                sympy_eq = lhs - rhs  # solve: expr = 0
            except Exception as e:
                raise ValueError(f"Cannot parse equation '{eq_expr}': {e}")
        else:
            try:
                sympy_eq = parse_expr(eq_expr, local_dict=local_ns, transformations=transformations)
            except Exception as e:
                raise ValueError(f"Cannot parse expression '{eq_expr}': {e}")
        
        if subs:
            sympy_eq = sympy_eq.subs(subs)
        
        solutions = solve(sympy_eq, var_sym)
        
        if not solutions:
            result_sym = sympy.EmptySet
            result_str = f"No solution found for {variable}"
            result_latex_str = r"\text{No solution}"
        else:
            result_sym = solutions
            # Format solutions
            sol_latex = [latex(s) for s in solutions]
            result_latex_str = f"{latex(var_sym)} = " + ",\\quad ".join(sol_latex)
            result_str = f"{variable} = " + ", ".join(str(s) for s in solutions)
            
            # Steps
            steps.append({"description": "Equation to solve", "latex": latex(sympy_eq) + " = 0"})
            for i, sol in enumerate(solutions):
                try:
                    n_val = float(N(sol, precision))
                    steps.append({"description": f"Solution {i+1}", "latex": f"{latex(var_sym)} = {latex(sol)} \\approx {n_val:.6g}"})
                except Exception:
                    steps.append({"description": f"Solution {i+1}", "latex": f"{latex(var_sym)} = {latex(sol)}"})
        
        # Try numeric for single solution
        if isinstance(solutions, list) and len(solutions) == 1:
            try:
                result_numeric = float(N(solutions[0], precision))
            except Exception:
                pass
        
        return (
            latex(sympy_eq) + " = 0",
            result_latex_str,
            result_numeric,
            steps,
            result_str,
            mode_used,
        )
    
    # ── Simplify mode ─────────────────────────────────────────────────────────
    if mode_used == "simplify":
        # Handle "simplify(...)" wrapper
        m_simplify_call = re.match(r'^\s*simplify\s*\((.+)\)\s*$', expr_clean, re.IGNORECASE)
        inner_expr = m_simplify_call.group(1).strip() if m_simplify_call else expr_clean
        
        try:
            sym_expr = parse_expr(inner_expr, local_dict=local_ns, transformations=transformations)
        except Exception as e:
            raise ValueError(f"Cannot parse expression '{inner_expr}': {e}")
        
        if subs:
            sym_expr = sym_expr.subs(subs)
        
        result_sym = simplify(sym_expr)
        expr_latex_str = latex(sym_expr)
        result_latex_str = latex(result_sym)
        result_str = str(result_sym)
        
        steps.append({"description": "Original expression", "latex": expr_latex_str})
        steps.append({"description": "Simplified", "latex": result_latex_str})
        
        # Try factored form as an alternative
        try:
            factored = factor(result_sym)
            if factored != result_sym:
                steps.append({"description": "Factored form", "latex": latex(factored)})
        except Exception:
            pass
        
        try:
            result_numeric = float(N(result_sym, precision))
        except Exception:
            pass
        
        return (expr_latex_str, result_latex_str, result_numeric, steps, result_str, mode_used)
    
    # ── Differentiate mode ────────────────────────────────────────────────────
    if mode_used == "diff":
        m_diff_call = re.match(r'^\s*diff(?:erentiate)?\s*\((.+)\)\s*$', expr_clean, re.IGNORECASE)
        if m_diff_call:
            inner = m_diff_call.group(1).strip()
            # Check "diff(f, x)" or "diff(f, x, n)" syntax
            parts = [p.strip() for p in inner.split(',')]
            func_str = parts[0]
            if len(parts) >= 2:
                var_sym = Symbol(parts[1])
            n_order = int(parts[2]) if len(parts) >= 3 else 1
        else:
            func_str = expr_clean
            n_order = 1
        
        try:
            func_expr = parse_expr(func_str, local_dict=local_ns, transformations=transformations)
        except Exception as e:
            raise ValueError(f"Cannot parse function '{func_str}': {e}")
        
        if subs:
            func_expr = func_expr.subs(subs)
        
        result_sym = diff(func_expr, var_sym, n_order)
        
        expr_latex_str = f"\\frac{{d}}{{d{latex(var_sym)}}} \\left( {latex(func_expr)} \\right)"
        result_latex_str = latex(simplify(result_sym))
        result_str = str(result_sym)
        
        steps.append({"description": "Function", "latex": latex(func_expr)})
        steps.append({"description": f"Derivative with respect to ${latex(var_sym)}$", "latex": result_latex_str})
        
        try:
            result_numeric = float(N(result_sym, precision))
        except Exception:
            pass
        
        return (expr_latex_str, result_latex_str, result_numeric, steps, result_str, mode_used)
    
    # ── Integrate mode ────────────────────────────────────────────────────────
    if mode_used == "integrate":
        m_int_call = re.match(r'^\s*int(?:egrate)?\s*\((.+)\)\s*$', expr_clean, re.IGNORECASE)
        limits = None
        
        if m_int_call:
            inner = m_int_call.group(1).strip()
            # Could be: "f, x" or "f, (x, a, b)" for definite integral
            # or "f, x, a, b"
            # Try definite integral: f, (x, a, b)
            m_definite = re.match(
                r'^(.+),\s*\(\s*([a-zA-Z_]\w*)\s*,\s*(.+?)\s*,\s*(.+?)\s*\)\s*$',
                inner
            )
            if m_definite:
                func_str = m_definite.group(1).strip()
                var_sym = Symbol(m_definite.group(2).strip())
                lower = m_definite.group(3).strip()
                upper = m_definite.group(4).strip()
                limits = (var_sym, sympify(lower), sympify(upper))
            else:
                # Indefinite: "f, x"
                parts = [p.strip() for p in inner.split(',', 1)]
                func_str = parts[0]
                if len(parts) == 2:
                    var_sym = Symbol(parts[1])
        else:
            func_str = expr_clean
        
        try:
            func_expr = parse_expr(func_str, local_dict=local_ns, transformations=transformations)
        except Exception as e:
            raise ValueError(f"Cannot parse function '{func_str}': {e}")
        
        if subs:
            func_expr = func_expr.subs(subs)
        
        if limits:
            result_sym = integrate(func_expr, limits)
            expr_latex_str = (
                f"\\int_{{{latex(limits[1])}}}^{{{latex(limits[2])}}} {latex(func_expr)}\\, d{latex(var_sym)}"
            )
        else:
            result_sym = integrate(func_expr, var_sym)
            expr_latex_str = f"\\int {latex(func_expr)}\\, d{latex(var_sym)}"
        
        result_latex_str = latex(simplify(result_sym))
        result_str = str(result_sym)
        
        if limits:
            steps.append({"description": "Definite integral", "latex": expr_latex_str})
        else:
            steps.append({"description": "Indefinite integral (+ C)", "latex": expr_latex_str})
        steps.append({"description": "Result", "latex": result_latex_str})
        
        try:
            result_numeric = float(N(result_sym, precision))
        except Exception:
            pass
        
        return (expr_latex_str, result_latex_str, result_numeric, steps, result_str, mode_used)
    
    # ── Symbolic / Numeric modes ──────────────────────────────────────────────
    try:
        sym_expr = parse_expr(expr_clean, local_dict=local_ns, transformations=transformations)
    except Exception as e:
        raise ValueError(f"Cannot parse expression '{expr_clean}': {e}")
    
    if subs:
        sym_expr = sym_expr.subs(subs)
    
    expr_latex_str = latex(sym_expr)
    
    if mode_used == "symbolic":
        result_sym = simplify(sym_expr)
        result_latex_str = latex(result_sym)
        result_str = str(result_sym)
        try:
            result_numeric = float(N(result_sym, precision))
        except Exception:
            pass
    else:
        # Numeric — evaluate to decimal
        try:
            numeric_val = N(sym_expr, precision)
            result_sym = numeric_val
            result_latex_str = latex(numeric_val)
            result_numeric = float(numeric_val)
            result_str = str(numeric_val)
        except Exception as e:
            # Fall back to symbolic if numeric fails
            logger.debug(f"Numeric evaluation failed, falling back to symbolic: {e}")
            result_sym = simplify(sym_expr)
            result_latex_str = latex(result_sym)
            result_str = str(result_sym)
            mode_used = "symbolic"
    
    return (expr_latex_str, result_latex_str, result_numeric, [], result_str, mode_used)


# ── Skill class ───────────────────────────────────────────────────────────────

class CalculateSkill(BaseSkill):
    """
    Math calculate skill.
    
    Executes sympy/mpmath computations in a thread pool (CPU-bound) to avoid
    blocking the async event loop. Results are returned immediately without
    going through a Celery task queue — calculations are fast (<1s typical).
    """
    
    def __init__(
        self,
        app,
        app_id: str,
        skill_id: str,
        skill_name: str,
        skill_description: str,
        stage: str = "development",
        full_model_reference: Optional[str] = None,
        pricing_config: Optional[Dict[str, Any]] = None,
        celery_producer: Any = None,
        skill_operational_defaults: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(
            app=app,
            app_id=app_id,
            skill_id=skill_id,
            skill_name=skill_name,
            skill_description=skill_description,
            stage=stage,
            full_model_reference=full_model_reference,
            pricing_config=pricing_config,
            celery_producer=celery_producer,
        )
    
    async def execute(
        self,
        request: CalculateRequest,
        secrets_manager: Any = None,
        **kwargs: Any,
    ) -> CalculateResponse:
        """
        Execute the calculate skill.
        
        Runs sympy computation in a thread pool to avoid blocking the event loop,
        then returns a structured response with LaTeX-formatted expression and result.
        """
        expression = request.expression.strip()
        if not expression:
            return CalculateResponse(error="Expression cannot be empty")
        
        logger.info(f"[math.calculate] Evaluating: mode={request.mode!r} expr={expression[:120]!r}")
        
        loop = asyncio.get_event_loop()
        
        try:
            # Run sympy in thread pool — it's CPU-bound and can take >1ms
            (
                expression_latex,
                result_latex,
                result_numeric,
                raw_steps,
                result_str,
                mode_used,
            ) = await loop.run_in_executor(
                None,
                _sympy_compute,
                expression,
                request.mode,
                request.variable,
                request.precision,
            )
        except ValueError as e:
            logger.warning(f"[math.calculate] ValueError: {e}")
            return CalculateResponse(
                expression_latex=expression,
                error=str(e),
            )
        except Exception as e:
            logger.error(f"[math.calculate] Unexpected error: {e}", exc_info=True)
            return CalculateResponse(
                expression_latex=expression,
                error=f"Computation failed: {e}",
            )
        
        steps = [CalculateStep(**s) for s in raw_steps]
        
        logger.info(
            f"[math.calculate] Done: mode_used={mode_used!r} "
            f"result={result_str[:80]!r}"
        )
        
        return CalculateResponse(
            expression_latex=expression_latex,
            result_latex=result_latex,
            result_numeric=result_numeric,
            result_str=result_str,
            steps=steps,
            mode_used=mode_used,
        )
