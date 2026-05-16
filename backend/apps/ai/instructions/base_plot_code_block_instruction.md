**Math Plot Rendering**

When you want to display an interactive graph or function plot, output a `plot` code fence:

~~~
```plot
f(x) = sin(x)
```
~~~

**Supported syntax:**
- One or more function definitions: `f(x) = <expression>`
- Standard math functions: `sin(x)`, `cos(x)`, `tan(x)`, `exp(x)`, `log(x)`, `sqrt(x)`, `abs(x)`
- Arithmetic operators: `+`, `-`, `*`, `/`, `^` (exponentiation)
- Constants: `pi`; use `exp(x)` for Euler exponentials instead of `e^x`
- Multiple functions on separate lines for overlaid plots:
  ```
  f(x) = sin(x)
  g(x) = cos(x)
  ```

**When to use plot:**
- User asks to graph, plot, or visualize a function or equation
- Explaining trigonometry, calculus, or any topic where seeing the curve helps understanding
- Comparing multiple functions visually

**Rules:**
- Always use `f(x) =` syntax — do NOT write raw expressions like just `sin(x)`
- Only use `x` as the independent variable (other variables are not supported)
- Keep the fence language exactly as `plot` (lowercase, no spaces)
- Write exponentials with `exp(...)`, for example `f(x) = cos(10 * exp(-0.5 * x))`
- Do NOT use the `plot` fence for data charts or histograms — only for mathematical functions
