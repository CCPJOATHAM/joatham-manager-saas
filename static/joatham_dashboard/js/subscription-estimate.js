"use strict";

// A fresh view is derived for every selection; an unavailable rate is never sticky.
window.JoathamSubscriptionEstimate = (() => {
    function number(value) {
        if (!["string", "number"].includes(typeof value) || String(value).trim() === "") return null;
        const parsed = Number(value);
        return Number.isFinite(parsed) ? parsed : null;
    }

    function present(data, locale, currentCurrency, unavailableText) {
        const currency = String(currentCurrency || "").trim().toUpperCase();
        const reference = number(data?.amount_usd);
        const amount = number(data?.estimated_amount);
        const rate = number(data?.exchange_rate);
        const available = /^[A-Z]{3}$/.test(currency)
            && data?.currency_code === currency
            && reference !== null && reference >= 0
            && amount !== null && amount >= 0
            && rate !== null && rate > 0;
        const format = (value, maximumFractionDigits = 2) => new Intl.NumberFormat(locale || "fr", {
            minimumFractionDigits: 2, maximumFractionDigits,
        }).format(value);
        return {
            currency, available,
            reference: reference !== null && reference >= 0 ? format(reference) : "—",
            amount: available ? format(amount) : unavailableText,
            rate: available ? format(rate, 8) : "—",
        };
    }
    return {present};
})();
