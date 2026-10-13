// Average of the positive values in an array.
function averagePositive(values) {
    let total = 0;
    let count = 0;
    for (const v of values) {
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
