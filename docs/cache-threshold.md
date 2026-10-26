# Semantic cache threshold sweep

Reproduce: `python -m app.eval.cache_threshold`.

39 pairs across 4 domains: 17 rewordings (should hit), 22 near-misses whose answer differs (must not hit). Cosine similarity from the production embedding model.

| Threshold | Rewordings served (cosine only) | Near-misses wrongly served (cosine only) | Rewordings served (+ figure guard) | Near-misses wrongly served (+ figure guard) |
|---:|---:|---:|---:|---:|
| 0.80 | 100% | 91% | 100% | 45% |
| 0.81 | 100% | 91% | 100% | 45% |
| 0.82 | 100% | 86% | 100% | 41% |
| 0.83 | 100% | 82% | 100% | 36% |
| 0.84 | 88% | 77% | 88% | 32% |
| 0.85 | 82% | 77% | 82% | 32% |
| 0.86 | 82% | 77% | 82% | 32% |
| 0.87 | 82% | 77% | 82% | 32% |
| 0.88 | 82% | 73% | 82% | 27% |
| 0.89 | 82% | 68% | 82% | 23% |
| 0.90 | 82% | 68% | 82% | 23% |
| 0.91 | 71% | 68% | 71% | 23% |
| 0.92 **(current)** | 59% | 68% | 59% | 23% |
| 0.93 | 47% | 68% | 47% | 23% |
| 0.94 | 29% | 55% | 29% | 18% |
| 0.95 | 29% | 55% | 29% | 18% |
| 0.96 | 29% | 50% | 29% | 18% |
| 0.97 | 24% | 36% | 24% | 9% |
| 0.98 | 24% | 36% | 24% | 9% |

### Every pair, highest similarity first

| Cosine | Label | Same figures | Domain | Change |
|---:|---|---|---|---|
| 1.000 | different | no | b2b_sla | hero prompt with `62% monthly uptime, and added…` → `92% monthly uptime, and added…` |
| 1.000 | different | no | b2b_sla | hero prompt with `48,000 for Managed Kubernetes,…` → `60,000 for Managed Kubernetes,…` |
| 0.999 | different | no | bc_tenancy_cra | hero prompt with `6% ($2,544) starting next mont…` → `2% ($2,448) starting next mont…` |
| 0.999 | different | no | bc_tenancy_cra | hero prompt with `3 months before withdrawing it…` → `8 months before withdrawing it…` |
| 0.999 | different | no | travel_appr | hero prompt with `6.5 hours due to a crew schedu…` → `9.5 hours due to a crew schedu…` |
| 0.997 | different | no | travel_appr | hero prompt with `1 passenger. Under Canadian AP…` → `3 passengers. Under Canadian A…` |
| 0.994 | different | yes | nutrition | hero prompt with `double Habanero Jack cheese, N…` → `no cheese, Nashville-Style Hot…` |
| 0.988 | different | yes | travel_appr | What is the free checked baggage allowance for a Star Alliance Gold member on an international Air Canada flight? → What is the free checked baggage allowance for a Star Alliance Gold member on a domestic Air Canada flight? |
| 0.987 | same | yes | nutrition | How much sodium is in the Chipotle Southwest sauce? → What's the sodium content of Chipotle Southwest sauce? |
| 0.986 | same | yes | bc_tenancy_cra | hero prompt with `I pay $2,400/month rent in New…` → `My rent in New Westminster, BC…` |
| 0.982 | same | yes | travel_appr | hero prompt with `My Air Canada flight from Vanc…` → `Crew scheduling shortages left…` |
| 0.981 | same | yes | b2b_sla | hero prompt with `Audit Northwind Cloud Invoice…` → `Please audit Northwind Cloud I…` |
| 0.967 | different | yes | travel_appr | What does APPR pay for a 4 hour delay on a large carrier? → What does APPR pay for a 4 hour delay on a small carrier? |
| 0.963 | different | yes | nutrition | hero prompt with `Rotisserie-Style Chicken on It…` → `Turkey Breast on Italian Herbs…` |
| 0.962 | different | no | bc_tenancy_cra | What is the BC allowable rent increase for 2026? → What is the BC allowable rent increase for 2027? |
| 0.962 | same | yes | nutrition | hero prompt with `Audit this exact custom footlo…` → `Check this custom footlong aga…` |
| 0.960 | different | no | bc_tenancy_cra | What is the TFSA penalty on a $4,500 excess held for 3 months? → What is the TFSA penalty on a $4,500 excess held for 1 month? |
| 0.938 | same | yes | travel_appr | When do Aeroplan points expire? → How long until my Aeroplan points expire if my account is inactive? |
| 0.937 | different | no | travel_appr | What does APPR pay for a 6 hour delay on a large carrier? → What does APPR pay for a 9 hour delay on a large carrier? |
| 0.937 | same | yes | b2b_sla | What priority is a password reset ticket? → How should a ticket asking to reset a password be prioritised? |
| 0.937 | different | yes | b2b_sla | How long are daily snapshots retained? → How long are monthly snapshots retained? |
| 0.936 | same | yes | nutrition | Is Habanero Jack cheese dairy-free? → Does Habanero Jack cheese contain milk? |
| 0.934 | different | no | travel_appr | Can I cancel my Air Canada ticket for free within 24 hours of booking? → Can I cancel my Air Canada ticket for free 3 days after booking? |
| 0.923 | same | yes | bc_tenancy_cra | How much notice must a BC landlord give for a rent increase? → How many months' notice does a landlord in BC need to give before raising rent? |
| 0.922 | same | yes | nutrition | How many calories are in a footlong Italian (white) bread? → What's the kcal count for the footlong Italian white bread? |
| 0.917 | same | yes | travel_appr | What is the free checked baggage allowance for a Star Alliance Gold member on an international Air Canada flight? → How many free checked bags does a Star Alliance Gold flyer get on an Air Canada international trip? |
| 0.913 | same | yes | b2b_sla | How long are audit logs retained? → For how many years do we keep audit logs? |
| 0.909 | same | yes | travel_appr | How long must a flight be delayed to get APPR compensation on a large carrier? → What's the minimum delay before a big airline owes APPR compensation? |
| 0.903 | same | yes | b2b_sla | What is the on-call stipend per week? → How much are on-call engineers paid weekly as a stipend? |
| 0.886 | different | yes | nutrition | How many calories are in a footlong Turkey Breast portion? → How many calories are in a six-inch Turkey Breast portion? |
| 0.876 | different | yes | b2b_sla | What service credit applies at 99.5% uptime under the Northwind SLA? → What service credit applies at 99.5% uptime under the Helix SLA? |
| 0.848 | same | yes | travel_appr | How long do I have to report a delayed bag? → What's the deadline for filing a delayed baggage claim? |
| 0.838 | same | yes | bc_tenancy_cra | Can my landlord evict me so his cousin can move in? → Is a cousin moving in a valid reason for my BC landlord to end my tenancy? |
| 0.832 | different | yes | bc_tenancy_cra | Can my landlord evict me so his cousin can move in? → Can my landlord evict me so his daughter can move in? |
| 0.830 | same | yes | bc_tenancy_cra | What is the TFSA over-contribution penalty rate? → How much does the CRA charge per month on excess TFSA contributions? |
| 0.826 | different | yes | bc_tenancy_cra | How long do I have to dispute a four-month notice to end tenancy? → How long do I have to file a bad-faith claim after my tenancy ends? |
| 0.812 | different | yes | nutrition | How much sodium is in the Chipotle Southwest sauce? → How much sodium is in the Nashville-Style Hot Sauce? |
| 0.796 | different | yes | nutrition | Is the Nashville-Style Hot Sauce dairy-free? → Is the Chipotle Southwest sauce dairy-free? |
| 0.634 | different | yes | b2b_sla | What priority is a password reset ticket? → What priority is a request to resend an invoice PDF? |
