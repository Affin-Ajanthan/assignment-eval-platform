def bubble_sort(items):
    """Sort a list of numbers in ascending order."""
    n = len(items)
    for i in range(n):
        for j in range(0, n - i - 1):
            if items[j] > items[j + 1]:
                items[j], items[j + 1] = items[j + 1], items[j]
    return items


if __name__ == "__main__":
    print(bubble_sort([5, 2, 9, 1, 5, 6]))
