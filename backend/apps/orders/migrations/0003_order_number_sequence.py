"""Dedicated sequence for human-facing order numbers.

`MAX(number) + 1` and `COUNT(*)` both race: two customers checking out in the same
instant would receive the same order number, and `number` is unique, so one checkout
would fail at the database. A sequence is atomic and never reuses a value.

Starting at 10000 so the platform's first sale is not visibly #1.
"""

from django.db import migrations

START = 10_000


class Migration(migrations.Migration):
    dependencies = [("orders", "0002_order_orderevent_orderitem_and_more")]

    operations = [
        migrations.RunSQL(
            sql=f"CREATE SEQUENCE IF NOT EXISTS order_number_seq START WITH {START} INCREMENT BY 1;",
            reverse_sql="DROP SEQUENCE IF EXISTS order_number_seq;",
        ),
    ]
