public static class Stats
{
    // Average of the positive values in an array.
    public static double AveragePositive(int[] values)
    {
        double total = 0;
        int count = 0;
        foreach (int v in values)
        {
            // skip zero and negative values
            if (v > 0)
            {
                total = total + v;
                count = count + 1;
            }
        }
        if (count == 0)
        {
            return 0;
        }
        return total / count;
    }
}
