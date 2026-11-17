"""A basic real-number calculator with an interactive command-line interface."""

import math


def calculate(left: float, operation: str, right: float) -> float:
    """Calculate a binary operation on finite real numbers.

    Supported operators are +, -, *, /, %, and ** (or ^ for powers).
    Invalid operators, non-finite numbers, and non-real results raise ValueError.
    Zero divisors raise ZeroDivisionError; oversized results raise OverflowError.
    """
    if operation not in ("+", "-", "*", "/", "%", "**", "^"):
        raise ValueError("Unsupported operator. Use +, -, *, /, %, **, or ^.")
    if not math.isfinite(left) or not math.isfinite(right):
        raise ValueError("Operands must be finite real numbers.")

    if operation == "+":
        result = left + right
    elif operation == "-":
        result = left - right
    elif operation == "*":
        result = left * right
    elif operation == "/":
        if right == 0:
            raise ZeroDivisionError("Cannot divide by zero.")
        result = left / right
    elif operation == "%":
        if right == 0:
            raise ZeroDivisionError("Cannot take modulo by zero.")
        result = left % right
    else:
        if left == 0 and right < 0:
            raise ZeroDivisionError("Zero cannot be raised to a negative power.")
        if left < 0 and right != math.trunc(right):
            raise ValueError("A negative base requires an integer exponent.")
        result = math.pow(left, right)

    if not math.isfinite(result):
        raise OverflowError("Result is too large to represent as a finite number.")
    return result


def main() -> None:
    """Prompt for calculations until the user quits or closes standard input."""
    print("Basic Calculator")
    print("Operators: +  -  *  /  %  ** (or ^)")
    print("Enter q at any prompt to quit.")

    while True:
        try:
            operation = input("Operator: ").strip()
            if operation.lower() in ("q", "quit", "exit"):
                break
            if operation not in ("+", "-", "*", "/", "%", "**", "^"):
                print("Error: Unsupported operator. Use +, -, *, /, %, **, or ^.")
                continue

            operands = []
            for prompt in ("First number: ", "Second number: "):
                text = input(prompt).strip()
                if text.lower() in ("q", "quit", "exit"):
                    print("Goodbye!")
                    return
                try:
                    operands.append(float(text))
                except ValueError:
                    raise ValueError("Please enter a valid number.") from None

            result = calculate(operands[0], operation, operands[1])
            print(f"Result: {result}")
        except (ValueError, ArithmeticError) as error:
            print(f"Error: {error}")
        except (EOFError, KeyboardInterrupt):
            print()
            break

    print("Goodbye!")


if __name__ == "__main__":
    main()