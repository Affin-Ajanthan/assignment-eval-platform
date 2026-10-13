# Average of the positive values in a list.
def average_positive(values):
    total = 0
    count = 0
    for v in values:
        # skip zero and negative values
        if v > 0:
            total = total + v
            count = count + 1
    if count == 0:
        return 0
    return total / count
