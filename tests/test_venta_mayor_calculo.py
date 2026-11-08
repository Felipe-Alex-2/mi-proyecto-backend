from decimal import Decimal
import pytest
from app.servicios.venta_mayor_service import summary, discount_lines


@pytest.mark.parametrize('percent', [13, 15])
@pytest.mark.parametrize('quantity', [1, 12, 13, 14, 26, 39, 100])
def test_one_discount_on_the_total_without_accumulating_blocks(quantity, percent):
    result = summary(Decimal('10') * quantity, quantity, percent)
    expected_percent = percent if quantity >= 13 else 0
    assert result['wholesale_discount_percent'] == expected_percent
    assert result['total_amount'] == Decimal('10') * quantity * (100-expected_percent) / 100


@pytest.mark.parametrize('percent', [13, 15])
def test_cent_allocation_keeps_receipt_lines_equal_to_the_exact_charged_total(percent):
    lines, result = discount_lines([
        dict(variant_id='a', quantity=7, unit_price=19.99),
        dict(variant_id='b', quantity=6, unit_price=7.93),
    ], percent)
    assert sum(Decimal(str(i['subtotal'])) for i in lines) == result['total_amount']
    assert sum(Decimal(str(i['wholesale_discount_amount'])) for i in lines) == result['wholesale_discount_amount']
    assert result['subtotal_before_wholesale'] == Decimal('187.51')
    assert all(i['original_unit_price'] in [19.99, 7.93] for i in lines)
