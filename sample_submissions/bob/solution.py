def sort_list(values):
    """Sort a list of numbers in ascending order."""
    length = len(values)
    for a in range(length):
        for b in range(0, length - a - 1):
            if values[b] > values[b + 1]:
                values[b], values[b + 1] = values[b + 1], values[b]
    return values


if __name__ == "__main__":
    print(sort_list([5, 2, 9, 1, 5, 6]))
