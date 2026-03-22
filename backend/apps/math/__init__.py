# backend/apps/math/__init__.py
#
# CRITICAL: This package is named 'math', which shadows Python's stdlib 'math'
# C-extension module when PYTHONPATH=/app is set and this code lives at /app/math/.
#
# Fix: locate the real math .so file in the dynload directory using glob,
# then load it directly via importlib.util.spec_from_file_location, bypassing
# sys.path entirely.  Once loaded we register it as sys.modules['math'] so
# all subsequent `import math` / `from math import ...` calls get the real module.

import sys as _sys
import glob as _glob
import importlib.util as _importlib_util

# Find the real stdlib math C-extension (.so) in lib-dynload.
# The file is never inside /app (our app root), so we filter those out as a
# safety measure.  On Python 3.13 it is typically at:
#   /usr/local/lib/python3.13/lib-dynload/math.cpython-313-*.so
_dynload_pattern = "/usr/local/lib/python3*/lib-dynload/math.cpython-*.so"
_math_so_candidates = [
    p for p in _glob.glob(_dynload_pattern)
    if not p.startswith("/app")
]

if not _math_so_candidates:
    raise ImportError(
        "Could not locate the stdlib 'math' C-extension (.so) via glob pattern "
        f"'{_dynload_pattern}'.  The 'math' package name conflicts with the Python "
        "stdlib 'math' module — cannot proceed without the real module."
    )

# Use the first match (there will only ever be one per Python version).
_math_so_path = _math_so_candidates[0]
_math_spec = _importlib_util.spec_from_file_location("math", _math_so_path)
if _math_spec is None or _math_spec.loader is None:
    raise ImportError(
        f"importlib could not create a ModuleSpec for '{_math_so_path}'.  "
        "Cannot load the real stdlib 'math' module."
    )

_real_math = _importlib_util.module_from_spec(_math_spec)
_math_spec.loader.exec_module(_real_math)  # type: ignore[union-attr]

# Register as the canonical 'math' so all future `import math` calls
# get the real module, not this package.
_sys.modules["math"] = _real_math

# Re-export all public symbols so that `from math import log, sin, ...` works
# for callers whose local frame already has our package object bound as 'math'.
acos = _real_math.acos
acosh = _real_math.acosh
asin = _real_math.asin
asinh = _real_math.asinh
atan = _real_math.atan
atan2 = _real_math.atan2
atanh = _real_math.atanh
ceil = _real_math.ceil
comb = _real_math.comb
copysign = _real_math.copysign
cos = _real_math.cos
cosh = _real_math.cosh
degrees = _real_math.degrees
dist = _real_math.dist
e = _real_math.e
erf = _real_math.erf
erfc = _real_math.erfc
exp = _real_math.exp
expm1 = _real_math.expm1
fabs = _real_math.fabs
factorial = _real_math.factorial
floor = _real_math.floor
fmod = _real_math.fmod
frexp = _real_math.frexp
fsum = _real_math.fsum
gamma = _real_math.gamma
gcd = _real_math.gcd
hypot = _real_math.hypot
inf = _real_math.inf
isclose = _real_math.isclose
isfinite = _real_math.isfinite
isinf = _real_math.isinf
isnan = _real_math.isnan
isqrt = _real_math.isqrt
lcm = _real_math.lcm
ldexp = _real_math.ldexp
lgamma = _real_math.lgamma
log = _real_math.log
log10 = _real_math.log10
log1p = _real_math.log1p
log2 = _real_math.log2
modf = _real_math.modf
nan = _real_math.nan
nextafter = _real_math.nextafter
perm = _real_math.perm
pi = _real_math.pi
pow = _real_math.pow
prod = _real_math.prod
radians = _real_math.radians
remainder = _real_math.remainder
sin = _real_math.sin
sinh = _real_math.sinh
sqrt = _real_math.sqrt
tan = _real_math.tan
tanh = _real_math.tanh
tau = _real_math.tau
trunc = _real_math.trunc
ulp = _real_math.ulp
