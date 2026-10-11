from decimal import Decimal, InvalidOperation

def build_count(value):
    try:
        count=Decimal(str(value))
        if not count.is_finite() or count<1 or count>10000 or count!=count.to_integral_value(): raise ValueError()
        return int(count)
    except (ValueError, InvalidOperation):
        raise ValueError('Choose a whole number of builds from 1 to 10,000.')
