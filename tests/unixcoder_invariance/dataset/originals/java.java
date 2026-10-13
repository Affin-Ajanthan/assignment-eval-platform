public class Stats {
    // Average of the positive values in an array.
    public static double averagePositive(int[] values) {
        double total = 0;
        int count = 0;
        for (int i = 0; i < values.length; i++) {
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
}
