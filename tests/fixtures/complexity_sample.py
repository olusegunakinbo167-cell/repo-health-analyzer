# Fixture files for complexity testing - known CC scores
#
# CC 1: simple function, no branches
def simple_add(a, b):
    return a + b


# CC 2: one if/else
def absolute(x):
    if x < 0:
        return -x
    else:
        return x


# CC 4: multiple branches
def categorize_score(score):
    if score >= 90:
        grade = "A"
    elif score >= 80:
        grade = "B"
    elif score >= 70:
        grade = "C"
    else:
        grade = "F"
    return grade


# CC 11: high risk (should be flagged, > 10)
# Multiple nested branches to push CC above 10
def high_risk_function(a, b, c, d, e):
    if a:
        x = 1
    else:
        x = 0
    if b:
        x += 1
    if c:
        x += 2
    elif d:
        x += 3
    else:
        x += 4
    for i in range(5):
        if e and i % 2 == 0:
            x += i
        elif i > 2:
            x -= i
    while x > 10:
        x -= 1
        if x % 3 == 0:
            break
    return x
