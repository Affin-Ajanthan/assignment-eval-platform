#include <vector>

// Average of the positive values in a vector.
double averagePositive(const std::vector<int> &values) {
    double total = 0;
    int count = 0;
    for (int v : values) {
        // skip zero and negative values
        if (v > 0) {
            total = total + v;
            count = count + 1;
        }
    }
    if (count == 0) {
        return 0;
    }
    return total / count;
}
