# Average of the positive values in a list.
def average_positive(values)
  total = 0
  count = 0
  values.each do |v|
    # skip zero and negative values
    if v > 0
      total = total + v
      count = count + 1
    end
  end
  return 0 if count == 0
  total.to_f / count
end
