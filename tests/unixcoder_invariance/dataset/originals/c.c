#include <stdio.h>

// Average of the positive values in an array.
double average_positive(const int *values, int n) {
    double total = 0;
    int count = 0;
    for (int i = 0; i < n; i++) {
        // skip zero and negative values
        if (values[i] > 0) {
            total = total + values[i];
            count = count + 1;
        }
    }
    if (count == 0) {
        return 0;
    }
    return total / count;
}
