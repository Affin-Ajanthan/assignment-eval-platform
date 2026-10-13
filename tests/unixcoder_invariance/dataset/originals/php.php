<?php
// Average of the positive values in an array.
function averagePositive(array $values) {
    $total = 0;
    $count = 0;
    foreach ($values as $v) {
        // skip zero and negative values
        if ($v > 0) {
            $total = $total + $v;
            $count = $count + 1;
        }
    }
    if ($count == 0) {
        return 0;
    }
    return $total / $count;
}
