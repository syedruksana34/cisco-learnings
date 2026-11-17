# Basic Python Calculator

A dependency-free command-line calculator for finite real numbers.
Requires Python 3.9 or newer.

## Run

From this directory:

```sh
python3 main.py
```

Choose an operator, then enter two numbers. Calculations repeat until you enter
`q`, `quit`, or `exit` at any prompt. Ctrl+C or end-of-input also exits cleanly.
After invalid input or a calculation error, start again with an operator.

| Operation | Operator | Example |
|-----------|----------|---------|
| Addition | `+` | `2 + 3 = 5` |
| Subtraction | `-` | `2 - 3 = -1` |
| Multiplication | `*` | `2 * 3 = 6` |
| Division | `/` | `7 / 2 = 3.5` |
| Modulo (remainder) | `%` | `7 % 3 = 1` |
| Power | `**` or `^` | `2 ** 3 = 8` |

Numbers may be negative, decimal, or scientific notation (such as `1e3`).
Python floating-point precision applies, so some decimal results are approximate.
Modulo follows Python's convention: the remainder has the divisor's sign.
Powers support fractional and negative exponents; negative bases require integer
exponents. As in Python, `0 ** 0` is `1`.

Division/modulo by zero, zero to a negative power, non-real powers, non-finite
inputs (`nan`, `inf`), and overflowing results produce explicit errors.
This basic calculator does not evaluate expressions, run code, or support
complex numbers, scientific functions, or symbolic mathematics.

For programmatic use, import `calculate` from `main` and call
`calculate(2, "+", 3)`. Errors raise `ValueError`, `ZeroDivisionError`, or
`OverflowError` rather than returning a default result.

## Tests

From this directory:

```sh
python3 -m unittest discover -s . -p 'test_*.py' -v
```

The suite covers every operator with sign and magnitude matrices, integer and
fractional powers, signed zero, the largest finite floats, normal/subnormal
boundaries, underflow, overflow, and non-finite operands. CLI tests cover number
formats, invalid inputs at both operand prompts, repeated error recovery,
prompt order, help text, and exits at every prompt. Subprocess tests verify
the script entry point, piped end-of-input, error recovery, and side-effect-free
imports. These are representative boundary and behavior tests, not an exhaustive
enumeration of every possible numeric input.
