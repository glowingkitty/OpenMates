import sympy
import numpy
import matplotlib.pyplot as plt
from IPython.display import display

plt.close("all")
assert callable(display)
x = sympy.symbols("x")
print("math-dependencies-ok", sympy.expand((x + 1) ** 2), numpy.arange(3).tolist())
