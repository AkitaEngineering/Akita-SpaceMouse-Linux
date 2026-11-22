# Sales sheet

Akita SpaceMouse for Linux is model **ASM-LNX-CE**. That model is the Community Edition. It is licensed under GPL-3.0-only, it has no licence key, and a service agreement does not limit how many machines can install it.

The sellable items are service SKUs. Issue one signed agreement per order. The customer installs that file. Akita's support desk enforces the workstation count and included time when a bundle arrives.

Prices exclude tax. Use the SKUs for the billing customer's country. [Price list](COMMERCIAL.md) · [Service terms](SERVICE-TERMS.md) · [Support guide](SUPPORT.md)

## SKUs

| SKU | Name | Term | Workstations | Included time | Price before tax |
| --- | --- | --- | ---: | --- | ---: |
| ASM-SET-1-US | Remote setup, one workstation, up to 45 minutes | the service date | 1 | 45 minutes | US$109 |
| ASM-SET-1-CA | Remote setup, one workstation, up to 45 minutes | the service date | 1 | 45 minutes | C$149 |
| ASM-SET-1-EU | Remote setup, one workstation, up to 45 minutes | the service date | 1 | 45 minutes | €99 |
| ASM-SUP-H-US | On-demand troubleshooting, one hour | 12 months | no cap | 60 minutes | US$149 |
| ASM-SUP-H-CA | On-demand troubleshooting, one hour | 12 months | no cap | 60 minutes | C$169 |
| ASM-SUP-H-EU | On-demand troubleshooting, one hour | 12 months | no cap | 60 minutes | €119 |
| ASM-FLT-5-US | Fleet pilot, up to five workstations | 90 days | 5 | not capped | US$499 |
| ASM-FLT-5-CA | Fleet pilot, up to five workstations | 90 days | 5 | not capped | C$649 |
| ASM-FLT-5-EU | Fleet pilot, up to five workstations | 90 days | 5 | not capped | €449 |
| ASM-ROL-1-US | Assisted rollout, one additional workstation | 90 days | 1 | not capped | US$39 |
| ASM-ROL-1-CA | Assisted rollout, one additional workstation | 90 days | 1 | not capped | C$49 |
| ASM-ROL-1-EU | Assisted rollout, one additional workstation | 90 days | 1 | not capped | €39 |
| ASM-SUB-10-US | Monthly team support, up to ten workstations | one calendar month | 10 | 60 minutes | US$149 |
| ASM-SUB-10-CA | Monthly team support, up to ten workstations | one calendar month | 10 | 60 minutes | C$199 |
| ASM-SUB-10-EU | Monthly team support, up to ten workstations | one calendar month | 10 | 60 minutes | €139 |

A quantity multiplies that row. ASM-ROL-1-CA with quantity 20 is 20 workstations and C$980. Put every line for one order on one agreement so the customer has one file. Hourly lines add time and price. They do not remove a workstation cap that comes from the other lines.

A Canadian order for 25 matching workstations is ASM-FLT-5-CA plus ASM-ROL-1-CA quantity 20. The total is C$1,629 before tax.

## Quote

Send this with the [service terms](SERVICE-TERMS.md):

```text
Quote — Akita SpaceMouse for Linux
Software model: ASM-LNX-CE (Community Edition, GPL-3.0-only, no licence key)
Customer:
Billing country:
SKU and quantity:
Service dates (UTC):
Price before tax:
Tax:
Total:
Terms: SERVICE-TERMS.md
```

Work starts when the customer accepts the quote in writing. Invoice from Akita Engineering, Niagara Falls, Ontario, before the scheduled work unless the quote says otherwise.

## Issue the agreement

On the Akita machine that holds the issuer key:

```sh
spacemouse agreement issue \
  --customer "Northwind CAD" \
  --email it@northwind.example \
  --line ASM-FLT-5-CA \
  --line ASM-ROL-1-CA:20 \
  --starts 2026-12-01 \
  --out Northwind.json
```

Email `Northwind.json` to the customer. The customer installs it:

```sh
spacemouse agreement install Northwind.json
spacemouse agreement
```

To add time or seats later, issue a new agreement for the full current order and have the customer install that file in place of the old one. The desk treats the new agreement id as a new seat pool.

## Issuer key

The private key is `~/.config/spacemouse/issuer.key` and is mode 0600. Back it up offline. The matching public key ships in this repository as `akita-support.pub`.

Public key SHA-256: `41044626e6c18f46c4faebe158cf31b47c05a21fd91eb91a2885927c365496c1`

Losing the private key means new agreements need a new public key in a software release. Agreements already issued keep verifying with this public key for as long as it ships. Create a key only on a machine that does not already have one:

```sh
spacemouse agreement keygen --pub-out akita-support.pub
```

Do not replace `akita-support.pub` in a release unless you mean to rotate the key.
