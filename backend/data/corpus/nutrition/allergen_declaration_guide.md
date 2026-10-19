# Allergen Declaration Guide (hidden allergens by ingredient)

## 1. Why hidden allergens matter
Many people assume allergens are only in obvious items. In this demo dataset some breads and sauces contain milk or soy that is not visible from the item name. Always read the allergen column of the ingredient matrix.

## 2. Hidden dairy (milk)
- Italian Herbs & Cheese bread contains a baked cheese topping, so it contains milk. A "zero dairy" order cannot use it.
- Chipotle Southwest sauce contains buttermilk powder, so it contains milk, even though sauces are not usually considered dairy.
- Ranch sauce contains milk.
- Habanero Jack and American cheese contain milk.

## 3. Hidden soy
- Nashville-Style Hot Sauce contains soy (soybean oil) and egg. It does not contain milk.
- Chipotle Southwest sauce contains soy and egg in addition to milk.
- Italian (white) and Multigrain bread contain soy flour.
- Steak is marinated with soy.

## 4. Items with no listed allergens
Rotisserie-Style Chicken, Turkey Breast, Yellow Mustard, Oil & Vinegar and the vegetable toppings (jalapenos, black olives, lettuce, tomatoes, pickles, spinach) have no listed allergens. Crispy onions contain wheat.

## 5. Quick answers
- Is Habanero Jack cheese dairy-free? No. It contains milk.
- Which items on a custom order are dairy-free? Only items with no milk in the allergen column.
- Cross-contact: the demo does not model cross-contact between ingredients prepared on the same line.

*Demo knowledge base; not legal, tax or medical advice. Numbers are illustrative.*
