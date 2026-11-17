"""Tests for calculator operations, errors, and command-line behavior."""

import io
import math
import operator
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from main import calculate, main


class CalculateTests(unittest.TestCase):
    def test_arithmetic_operations(self) -> None:
        cases = [
            (2, "+", 3, 5),
            (-2, "+", 3, 1),
            (0, "+", 0, 0),
            (0.1, "+", 0.2, 0.3),
            (2, "-", 3, -1),
            (-2, "-", -3, 1),
            (2.5, "-", 0.5, 2),
            (2, "*", 3, 6),
            (-2, "*", 3, -6),
            (0, "*", 3, 0),
            (1.5, "*", 2.5, 3.75),
            (7, "/", 2, 3.5),
            (-7, "/", 2, -3.5),
            (0, "/", 2, 0),
            (7, "%", 3, 1),
            (-7, "%", 3, 2),
            (7, "%", -3, -2),
            (5.5, "%", 2, 1.5),
            (0, "%", 3, 0),
        ]
        for left, operation, right, expected in cases:
            with self.subTest(left=left, operation=operation, right=right):
                self.assertAlmostEqual(calculate(left, operation, right), expected)

    def test_powers(self) -> None:
        for operation in ("**", "^"):
            for left, right, expected in [
                (2, 3, 8),
                (2, -2, 0.25),
                (9, 0.5, 3),
                (-2, 3, -8),
                (-2, 2, 4),
                (5, 0, 1),
                (0, 0, 1),
                (0, 2, 0),
            ]:
                with self.subTest(operation=operation, left=left, right=right):
                    self.assertAlmostEqual(calculate(left, operation, right), expected)

    def test_zero_divisors(self) -> None:
        for operation in ("/", "%"):
            for zero in (0.0, -0.0):
                with self.subTest(operation=operation, zero=zero):
                    with self.assertRaises(ZeroDivisionError):
                        calculate(5, operation, zero)

    def test_zero_to_negative_power(self) -> None:
        for operation in ("**", "^"):
            with self.subTest(operation=operation):
                with self.assertRaises(ZeroDivisionError):
                    calculate(0, operation, -1)

    def test_non_real_power(self) -> None:
        for operation in ("**", "^"):
            with self.subTest(operation=operation):
                with self.assertRaisesRegex(ValueError, "integer exponent"):
                    calculate(-4, operation, 0.5)

    def test_unsupported_operators(self) -> None:
        for operation in ("", "//", "add", "&", " + "):
            with self.subTest(operation=operation):
                with self.assertRaisesRegex(ValueError, "Unsupported operator"):
                    calculate(2, operation, 3)

    def test_non_finite_operands(self) -> None:
        for operation in ("+", "-", "*", "/", "%", "**", "^"):
            for value in (math.inf, -math.inf, math.nan):
                for left, right in ((value, 2), (2, value)):
                    with self.subTest(operation=operation, left=left, right=right):
                        with self.assertRaisesRegex(ValueError, "finite real"):
                            calculate(left, operation, right)

    def test_overflow(self) -> None:
        for left, operation, right in [
            (1e308, "+", 1e308),
            (-1e308, "-", 1e308),
            (1e308, "*", 2),
            (1e308, "/", 1e-308),
            (1e308, "**", 2),
        ]:
            with self.subTest(operation=operation):
                with self.assertRaises(OverflowError):
                    calculate(left, operation, right)

    def test_arithmetic_sign_and_magnitude_matrix(self) -> None:
        operations = {
            "+": operator.add,
            "-": operator.sub,
            "*": operator.mul,
            "/": operator.truediv,
            "%": operator.mod,
        }
        values = (-1000.0, -2.5, -1.0, -0.0, 0.0, 0.125, 1.0, 2.5, 1000.0)
        for symbol, reference in operations.items():
            for left in values:
                for right in values:
                    with self.subTest(operation=symbol, left=left, right=right):
                        if symbol in ("/", "%") and right == 0:
                            with self.assertRaises(ZeroDivisionError):
                                calculate(left, symbol, right)
                        else:
                            self.assertEqual(
                                calculate(left, symbol, right),
                                reference(left, right),
                            )

    def test_power_sign_and_exponent_matrix(self) -> None:
        for symbol in ("**", "^"):
            for base in (-4.0, -1.0, -0.0, 0.0, 0.25, 1.0, 4.0):
                for exponent in (-3.0, -0.5, 0.0, 0.5, 2.0, 3.0):
                    with self.subTest(symbol=symbol, base=base, exponent=exponent):
                        if base == 0 and exponent < 0:
                            with self.assertRaises(ZeroDivisionError):
                                calculate(base, symbol, exponent)
                        elif base < 0 and not exponent.is_integer():
                            with self.assertRaises(ValueError):
                                calculate(base, symbol, exponent)
                        else:
                            self.assertEqual(
                                calculate(base, symbol, exponent),
                                math.pow(base, exponent),
                            )

    def test_finite_float_boundaries(self) -> None:
        largest = sys.float_info.max
        smallest_normal = sys.float_info.min
        smallest_subnormal = math.ulp(0.0)
        cases = [
            (largest, "+", 0.0, largest),
            (largest, "-", largest, 0.0),
            (largest, "/", largest, 1.0),
            (largest, "%", largest, 0.0),
            (largest, "*", 1.0, largest),
            (largest, "**", 1.0, largest),
            (smallest_normal, "/", 2.0, smallest_normal / 2.0),
            (smallest_subnormal, "+", smallest_subnormal, 2 * smallest_subnormal),
            (smallest_subnormal, "*", 1.0, smallest_subnormal),
            (smallest_subnormal, "/", smallest_subnormal, 1.0),
            (smallest_subnormal, "%", smallest_subnormal, 0.0),
        ]
        for left, symbol, right, expected in cases:
            with self.subTest(symbol=symbol, left=left, right=right):
                self.assertEqual(calculate(left, symbol, right), expected)

    def test_underflow_rounds_to_zero(self) -> None:
        for left, symbol, right in [
            (math.ulp(0.0), "/", 2.0),
            (math.ulp(0.0), "*", 0.5),
            (1e-200, "**", 2.0),
            (1e-200, "^", 2.0),
        ]:
            with self.subTest(symbol=symbol):
                self.assertEqual(calculate(left, symbol, right), 0.0)

    def test_signed_zero_results(self) -> None:
        for left, symbol, right, sign in [
            (-0.0, "+", -0.0, -1),
            (-0.0, "-", 0.0, -1),
            (-0.0, "*", 2.0, -1),
            (0.0, "*", -2.0, -1),
            (-0.0, "/", 2.0, -1),
            (0.0, "/", -2.0, -1),
            (4.0, "%", -2.0, -1),
            (-4.0, "%", 2.0, 1),
            (-0.0, "**", 3.0, -1),
            (-0.0, "^", 2.0, 1),
        ]:
            with self.subTest(left=left, symbol=symbol, right=right):
                result = calculate(left, symbol, right)
                self.assertEqual(result, 0.0)
                self.assertEqual(math.copysign(1.0, result), sign)

    def test_zero_divided_by_zero(self) -> None:
        for symbol in ("/", "%"):
            for left in (0.0, -0.0):
                for right in (0.0, -0.0):
                    with self.subTest(symbol=symbol, left=left, right=right):
                        with self.assertRaises(ZeroDivisionError):
                            calculate(left, symbol, right)

    def test_fractional_exponents_very_close_to_integer_are_rejected(self) -> None:
        for exponent in (math.nextafter(2.0, 0.0), math.nextafter(2.0, math.inf)):
            for symbol in ("**", "^"):
                with self.subTest(exponent=exponent, symbol=symbol):
                    with self.assertRaisesRegex(ValueError, "integer exponent"):
                        calculate(-2.0, symbol, exponent)

    def test_large_integer_exponents_for_unit_bases(self) -> None:
        for symbol in ("**", "^"):
            for base, exponent, expected in [
                (1.0, 1e308, 1.0),
                (-1.0, 1e308, 1.0),
                (-1.0, -3.0, -1.0),
            ]:
                with self.subTest(symbol=symbol, base=base, exponent=exponent):
                    self.assertEqual(calculate(base, symbol, exponent), expected)

    def test_overflow_at_float_limit(self) -> None:
        largest = sys.float_info.max
        for left, symbol, right in [
            (largest, "+", largest),
            (-largest, "-", largest),
            (-largest, "*", 2.0),
            (largest, "/", 0.5),
            (largest, "**", 2.0),
            (largest, "^", 2.0),
        ]:
            with self.subTest(symbol=symbol):
                with self.assertRaises(OverflowError):
                    calculate(left, symbol, right)

    def test_both_operands_non_finite(self) -> None:
        for symbol in ("+", "-", "*", "/", "%", "**", "^"):
            for left in (math.inf, -math.inf, math.nan):
                for right in (math.inf, -math.inf, math.nan):
                    with self.subTest(symbol=symbol, left=left, right=right):
                        with self.assertRaisesRegex(ValueError, "finite real"):
                            calculate(left, symbol, right)


class CommandLineTests(unittest.TestCase):
    def run_session(self, inputs: list[object]) -> str:
        with patch("builtins.input", side_effect=inputs):
            with patch("sys.stdout", new_callable=io.StringIO) as output:
                main()
                return output.getvalue()

    def test_each_operator(self) -> None:
        cases = [
            ("+", "5.0"),
            ("-", "-1.0"),
            ("*", "6.0"),
            ("/", str(2 / 3)),
            ("%", "2.0"),
            ("**", "8.0"),
            ("^", "8.0"),
        ]
        for operation, expected in cases:
            with self.subTest(operation=operation):
                output = self.run_session([operation, "2", "3", "q"])
                self.assertIn(f"Result: {expected}\n", output)
                self.assertIn("Goodbye!", output)

    def test_repeated_calculations_and_whitespace(self) -> None:
        output = self.run_session([" + ", " 1.5 ", "2.5", "*", "3", "4", " Q "])
        self.assertIn("Result: 4.0", output)
        self.assertIn("Result: 12.0", output)

    def test_invalid_operator_recovers(self) -> None:
        output = self.run_session(["bad", "+", "1", "2", "q"])
        self.assertIn("Error: Unsupported operator", output)
        self.assertIn("Result: 3.0", output)

    def test_invalid_number_recovers(self) -> None:
        for inputs in (["+", "abc"], ["+", "1", "abc"]):
            with self.subTest(inputs=inputs):
                output = self.run_session(inputs + ["+", "1", "2", "q"])
                self.assertIn("Error: Please enter a valid number.", output)
                self.assertIn("Result: 3.0", output)

    def test_calculation_errors_recover(self) -> None:
        for inputs, message in [
            (["/", "1", "0"], "Cannot divide by zero"),
            (["%", "1", "0"], "Cannot take modulo by zero"),
            (["^", "0", "-1"], "negative power"),
            (["^", "-1", "0.5"], "integer exponent"),
            (["+", "nan", "2"], "finite real numbers"),
            (["*", "1e308", "2"], "too large"),
            (["^", "1e308", "2"], "Error:"),
        ]:
            with self.subTest(inputs=inputs):
                output = self.run_session(inputs + ["+", "1", "2", "q"])
                self.assertIn(message, output)
                self.assertIn("Result: 3.0", output)

    def test_quit_at_every_prompt(self) -> None:
        for command in ("q", "Q", "quit", "EXIT"):
            for prefix in ([], ["+"], ["+", "1"]):
                with self.subTest(command=command, prefix=prefix):
                    output = self.run_session(prefix + [command])
                    self.assertEqual(output.count("Goodbye!"), 1)
                    self.assertNotIn("Error:", output)

    def test_eof_and_interrupt_at_every_prompt(self) -> None:
        for exception in (EOFError, KeyboardInterrupt):
            for prefix in ([], ["+"], ["+", "1"]):
                with self.subTest(exception=exception, prefix=prefix):
                    output = self.run_session(prefix + [exception()])
                    self.assertIn("Goodbye!", output)
                    self.assertNotIn("Error:", output)

    def test_script_entry_point(self) -> None:
        process = subprocess.run(
            [sys.executable, str(Path(__file__).with_name("main.py"))],
            input="+\n2\n3\nq\n",
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        )
        self.assertIn("Result: 5.0", process.stdout)
        self.assertIn("Goodbye!", process.stdout)
        self.assertEqual(process.stderr, "")

    def test_supported_number_formats(self) -> None:
        for text, expected in [
            ("+2", "2.0"),
            ("-2.5", "-2.5"),
            (".5", "0.5"),
            ("5.", "5.0"),
            ("1e3", "1000.0"),
            ("-2.5E-2", "-0.025"),
            ("1_000", "1000.0"),
            (" \t3.5\t ", "3.5"),
        ]:
            for numbers in ([text, "0"], ["0", text]):
                with self.subTest(text=text, numbers=numbers):
                    output = self.run_session(["+"] + numbers + ["q"])
                    self.assertIn(f"Result: {expected}\n", output)
                    self.assertNotIn("Error:", output)

    def test_invalid_number_formats_at_both_prompts(self) -> None:
        for text in ("", " ", "abc", "1,000", "1..2", "1e", "0x10", "2+3", "1/2", "3j"):
            for prefix in (["+"], ["+", "1"]):
                with self.subTest(text=text, prefix=prefix):
                    output = self.run_session(prefix + [text, "+", "2", "3", "q"])
                    self.assertEqual(output.count("Error:"), 1)
                    self.assertIn("Please enter a valid number.", output)
                    self.assertIn("Result: 5.0", output)

    def test_non_finite_number_formats_at_both_prompts(self) -> None:
        for text in ("nan", "NaN", "inf", "-inf", "+Infinity", "1e309", "-1e309"):
            for numbers in ([text, "2"], ["2", text]):
                with self.subTest(text=text, numbers=numbers):
                    output = self.run_session(["+"] + numbers + ["q"])
                    self.assertIn("Error: Operands must be finite real numbers.", output)
                    self.assertNotIn("Result:", output)

    def test_invalid_operator_formats(self) -> None:
        for text in ("", " ", "//", "***", "x", "ADD", "2+3", "sqrt", "&"):
            with self.subTest(text=text):
                output = self.run_session([text, "q"])
                self.assertEqual(output.count("Error:"), 1)
                self.assertIn("Unsupported operator", output)
                self.assertNotIn("Result:", output)

    def test_multiple_errors_then_success(self) -> None:
        output = self.run_session(
            ["bad", "+", "abc", "/", "1", "0", "^", "-1", ".5",
             "+", "nan", "2", "*", "1e308", "2", "-", "9", "4", "q"]
        )
        self.assertEqual(output.count("Error:"), 6)
        self.assertEqual(output.count("Result:"), 1)
        self.assertIn("Result: 5.0", output)
        self.assertEqual(output.count("Goodbye!"), 1)

    def test_startup_help(self) -> None:
        output = self.run_session(["q"])
        self.assertIn("Basic Calculator", output)
        self.assertIn("Operators: +  -  *  /  %  ** (or ^)", output)
        self.assertIn("Enter q at any prompt to quit.", output)
        self.assertNotIn("Result:", output)

    def test_prompt_order(self) -> None:
        with patch("builtins.input", side_effect=["+", "2", "3", "q"]) as read:
            with patch("sys.stdout", new_callable=io.StringIO):
                main()
        self.assertEqual(
            [call.args[0] for call in read.call_args_list],
            ["Operator: ", "First number: ", "Second number: ", "Operator: "],
        )

    def test_script_eof_at_each_prompt(self) -> None:
        for text in ("", "+\n", "+\n2\n", "+\n2\n3\n"):
            with self.subTest(text=text):
                process = subprocess.run(
                    [sys.executable, str(Path(__file__).with_name("main.py"))],
                    input=text,
                    capture_output=True,
                    text=True,
                    timeout=5,
                    check=True,
                )
                self.assertEqual(process.stdout.count("Goodbye!"), 1)
                self.assertNotIn("Error:", process.stdout)
                self.assertEqual(process.stderr, "")
                if text == "+\n2\n3\n":
                    self.assertIn("Result: 5.0", process.stdout)
                else:
                    self.assertNotIn("Result:", process.stdout)

    def test_script_error_recovery(self) -> None:
        process = subprocess.run(
            [sys.executable, str(Path(__file__).with_name("main.py"))],
            input="/\n1\n0\n*\n6\n7\nexit\n",
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        )
        self.assertIn("Error: Cannot divide by zero.", process.stdout)
        self.assertIn("Result: 42.0", process.stdout)
        self.assertEqual(process.stdout.count("Goodbye!"), 1)
        self.assertEqual(process.stderr, "")

    def test_import_has_no_interactive_side_effects(self) -> None:
        process = subprocess.run(
            [sys.executable, "-c", "import main"],
            cwd=Path(__file__).parent,
            input="",
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        )
        self.assertEqual(process.stdout, "")
        self.assertEqual(process.stderr, "")


if __name__ == "__main__":
    unittest.main()
