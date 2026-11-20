"use strict";

// Integer cents and percentage basis points keep previews aligned with Decimal.
window.JoathamInvoiceTotals = (() => {
    function hundredths(value) {
        const match = String(value || "0").match(/^([+-]?)(\d+)(?:[.,](\d{0,2}))?$/);
        if (!match) return 0n;
        const magnitude = BigInt(match[2]) * 100n + BigInt((match[3] || "").padEnd(2, "0"));
        return match[1] === "-" ? -magnitude : magnitude;
    }

    function decimal(cents) {
        const sign = cents < 0n ? "-" : "";
        const magnitude = cents < 0n ? -cents : cents;
        return `${sign}${magnitude / 100n}.${String(magnitude % 100n).padStart(2, "0")}`;
    }

    function roundPercentage(numerator) {
        const magnitude = numerator < 0n ? -numerator : numerator;
        const rounded = (magnitude + 5000n) / 10000n;
        return numerator < 0n ? -rounded : rounded;
    }

    function calculate(rows, rates) {
        let quantity = 0n;
        const lines = rows.map(row => {
            const count = /^\d+$/.test(String(row.quantity)) ? BigInt(row.quantity) : 0n;
            quantity += count;
            return count * hundredths(row.price);
        });
        const ht = lines.reduce((sum, line) => sum + line, 0n);
        const tax = ht * hundredths(rates.tva);
        const discount = ht * (hundredths(rates.remise) + hundredths(rates.rabais) + hundredths(rates.ristourne));
        return {
            lines: lines.map(decimal), quantity: String(quantity), ht: decimal(ht),
            tax: decimal(roundPercentage(tax)), discount: decimal(roundPercentage(discount)),
            // Round the final result, not the individually displayed components.
            net: decimal(roundPercentage(ht * 10000n + tax - discount)),
        };
    }
    return {calculate};
})();
