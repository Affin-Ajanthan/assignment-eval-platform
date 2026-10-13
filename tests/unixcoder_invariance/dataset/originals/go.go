package stats

// AveragePositive returns the average of the positive values.
func AveragePositive(values []int) float64 {
	total := 0
	count := 0
	for _, v := range values {
		// skip zero and negative values
		if v > 0 {
			total = total + v
			count = count + 1
		}
	}
	if count == 0 {
		return 0
	}
	return float64(total) / float64(count)
}
