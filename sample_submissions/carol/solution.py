def fibonacci(n):
    """Return the first n Fibonacci numbers."""
    a, b = 0, 1
    sequence = []
    for _ in range(n):
        sequence.append(a)
        a, b = b, a + b
    return sequence


if __name__ == "__main__":
    print(fibonacci(10))
