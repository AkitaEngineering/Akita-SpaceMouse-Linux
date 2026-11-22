# Service terms

These terms apply to paid setup, fleet deployment, and support for Akita SpaceMouse for Linux. A quote that names these terms, and the customer's written acceptance of that quote, form the service agreement. The signed agreement file records the SKU lines, dates, workstation count, and included time.

The supplier is Akita Engineering, 4551 Zimmerman Ave, Niagara Falls, Ontario L2E 3M5, Canada. Contact [info@akitaengineering.com](mailto:info@akitaengineering.com).

## Software and service

Model ASM-LNX-CE, the Community Edition, is licensed under GPL-3.0-only. These terms do not change that licence. There is no licence key. Installing, running, copying, and sharing the Community Edition does not require a service agreement and does not require payment.

A service agreement is Akita's promise to do the work named by its SKUs. Akita checks the agreement when it accepts a support bundle. An expired agreement, a signature that does not verify, a workstation past the covered count, or a used time allowance means that request is outside the agreement. The software on that workstation keeps running.

Dates in the agreement file are UTC calendar dates and include the start and end dates. A monthly SKU runs from the start date through the day before the same date next month. A pilot or rollout SKU runs for 90 days from the start date unless the quote states a different end date. Prepaid hours run for 12 months. A setup SKU covers the service date.

## What the fee covers

- **Remote setup** installs the Community Edition and the Linux driver on the covered workstation, completes Onshape setup in one browser profile, and sets motion tuning and a button profile. The included time is 45 minutes per setup.
- **On-demand troubleshooting** is remote help with the driver, the browser setup, or device input for this software.
- **Fleet pilot** delivers a verified Onshape setup on one Linux distribution and one browser, one shared button profile, and a rollout and rollback guide, for up to five workstations.
- **Assisted rollout** covers each additional workstation that matches the piloted Linux distribution and browser.
- **Monthly team support** covers up to ten workstations and one pooled hour in the month. The initial response is the next business day, Monday to Friday, America/Toronto, excluding Ontario statutory holidays. That response is the first reply, not a promise that the issue is fixed that day.

Included time is counted in minutes when Akita closes the support case. The one-hour minimum applies to an on-demand hourly purchase. It does not round up time taken from a pool that is already paid.

Hardware, an Onshape subscription, on-site work, a second Linux or browser configuration, and general Linux administration are outside these SKUs. A change Onshape, a browser vendor, or a device maker makes after delivery is hourly work. A proprietary or white-label licence is not offered for this release.

## Customer duties

The customer names a contact, has the device connected for a scheduled session, and provides sudo access when the work needs it. For a diagnosis, the customer creates a bundle with `spacemouse support bundle` and sends that file to Akita. The customer installs the agreement file Akita sends with `spacemouse agreement install` on a covered workstation before asking that workstation to draw a seat.

## Diagnostic data

A support bundle can contain the product version, OS name and version, kernel, hostname, machine id, the spacenavd journal excerpt, the local launcher log, the bridge crash log, a list of core dumps for spacenavd and this application, the device name reported by spacenavd, the button profile, the driver configuration, and the service agreement.

The bundle does not contain browser passwords, page contents, or core dump files. Core dump files stay on the workstation. Akita reads a core dump only after asking for that file and receiving it in a separate message.

Akita uses the bundle to perform the requested service and to count covered workstations and time. The machine id from the first accepted bundle for a workstation holds that seat. A later bundle from the same machine id uses the same seat. A new machine id past the covered count is refused.

Akita may delete the log files in a case after the case is closed and the invoice is paid. The invoice, agreement id, machine ids, dates, and minutes are kept for six years.

## Fees

The quote states the SKUs, price, and tax. Akita invoices from Niagara Falls, Ontario, before the scheduled work unless the quote says otherwise. Canada GST/HST, United States state and local sales tax, and VAT are added when they apply. The invoice shows a tax registration number when the law requires one. Further time after the included minutes uses the hourly SKU for the billing country.

A monthly plan renews when the customer accepts the next invoice. Cancel in writing before the renewal date on the invoice.

## Care and liability

Akita will perform the service with reasonable skill and care. The Community Edition is provided under the GPL warranty disclaimer in the [license](LICENSE). Akita's liability arising from a service agreement is limited to the fees paid under that agreement. This limit does not apply to liability that the law does not allow to be limited, including liability for fraud or for death or personal injury caused by negligence.

## Law

These terms are governed by the laws of Ontario and the laws of Canada that apply there. The courts of Ontario have jurisdiction.

These terms are for business customers. A consumer in the European Union can ask for a separate quote that includes the tax and contract information required for that sale.
